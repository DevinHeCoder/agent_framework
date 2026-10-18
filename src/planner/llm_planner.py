"""LLM 规划器：让 LLM 做任务拆解、多步骤规划、自动选择工具（需求②核心）。

流程：
1. 把用户请求 + 可用工具 schema 组装进 system prompt；
2. 要求 LLM 只输出 JSON：{"steps": [{"action", "args", "thought"}, ...]}；
3. 用 json_parser 容错解析；输出非法时带错误重试（parse_retries）；
4. 校验步骤结构、按 max_steps 截断、自动补 respond 收尾步骤。

与 fake LLM 搭配可离线跑通全链路；与真实 LLM 搭配即真实拆解。
"""
import json
import re
from typing import Any, Dict, List, Optional

from src.common.exceptions import PlannerError
from src.llm_client.base import ChatMessage, LLMClient
from src.planner.base import BasePlanner, Plan, Step
from src.planner.registry import planner_registry
from src.utils.json_parser import try_parse_json_strict

_DEFAULT_SYSTEM_PROMPT = """你是任务规划器。请把用户请求拆解为最多 {max_steps} 个有序步骤。
可用工具（名称、说明、参数 Schema）：
{tools_desc}

规则：
1. 每一步要么调用一个工具（action=工具名，args 必须符合该工具参数 Schema），
   要么以 action="respond" 直接作答（respond 必须是最后一步，且不调用工具）。
2. 用户请求可直接回答（包括仅需结合「会话历史」即可回答的记忆类问题，
   如“我叫什么名字/我是谁/你记得吗/我之前说了什么”）时，只输出一个 respond
   步骤，不要调用工具。
3. 只输出 JSON，禁止输出任何其他文字。格式：
   {{"steps": [{{"action": "工具名", "args": {{...}}, "thought": "为什么这么做"}}]}}
4. args 中缺失的可选参数不要填；必填参数必须填。"""


@planner_registry.register("llm")
class LLMPlanner(BasePlanner):
    """基于 LLM 的任务规划器。"""

    def __init__(
        self,
        llm: LLMClient,
        max_steps: int = 6,
        parse_retries: int = 2,
        system_prompt_template: str = _DEFAULT_SYSTEM_PROMPT,
        plan_model: Optional[str] = None,
        logger=None,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.parse_retries = parse_retries
        self.system_prompt_template = system_prompt_template
        # 性能优化：规划可指定快模型（如 flash），空则使用 LLM 默认模型
        self.plan_model = plan_model or None
        self._logger = logger

    def plan(
        self,
        query: str,
        tools: Optional[List[Any]] = None,
        context: Optional[List[Any]] = None,
    ) -> Plan:
        # 性能优化：规则直配短路——纯计算/纯时间请求直接规划，不经过 LLM
        fast = _fast_plan_for(query)
        if fast is not None:
            return fast

        messages = [
            ChatMessage(
                role="system",
                content=self.system_prompt_template.format(
                    max_steps=self.max_steps,
                    tools_desc=_render_tools(tools),
                ),
            ),
            ChatMessage(role="user", content=_user_content_with_history(query, context)),
        ]

        last_error: Optional[Exception] = None
        for attempt in range(self.parse_retries + 1):
            raw = self.llm.chat(messages, temperature=0.0, model=self.plan_model)
            obj = try_parse_json_strict(raw)
            if obj is None:
                last_error = PlannerError(
                    f"规划输出不是合法 JSON（第 {attempt + 1} 次）：{raw[:200]!r}"
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content="你上次的输出不是合法 JSON，请只输出 JSON。"
                        f"上次输出：{raw[:200]}",
                    )
                )
                continue
            return self._build_plan(query, obj)

        raise last_error  # type: ignore[misc]

    # ---------------- 内部 ----------------
    def _build_plan(self, query: str, obj: Any) -> Plan:
        raw_steps = obj.get("steps") if isinstance(obj, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("规划结果缺少有效的 steps 列表")

        steps: List[Step] = []
        for i, item in enumerate(raw_steps[: self.max_steps]):
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if not isinstance(action, str) or not action:
                raise PlannerError(f"步骤 {i} 缺少 action")
            args = item.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            steps.append(
                Step(
                    step_id=i + 1,
                    action=action,
                    args=args,
                    thought=str(item.get("thought", "")),
                )
            )

        if not steps:
            raise PlannerError("规划结果为空")

        # 自动补 respond 收尾步骤，保证 Agent 总能产出最终回答
        if steps[-1].action != "respond":
            steps.append(Step(step_id=len(steps) + 1, action="respond", thought="总结以上结果"))
        return Plan(query=query, steps=steps)


def _user_content_with_history(
    query: str, context: Optional[List[Any]] = None
) -> str:
    """把会话历史拼进规划请求，让 LLM 能回答记忆类问题（如“我叫什么名字”）。

    只取最近 8 条、单条 160 字符，控制 prompt 长度；无历史时与原行为一致。
    """
    if not context:
        return f"用户请求：{query}"
    lines = []
    for m in context[-8:]:
        role = getattr(m, "role", "user")
        content = getattr(m, "content", str(m)) or ""
        content = content.replace("\n", " ")[:160]
        lines.append(f"{role}: {content}")
    return (
        "会话历史（可据此回答记忆类问题；若与当前问题无关可忽略）：\n"
        + "\n".join(lines)
        + f"\n\n用户请求：{query}"
    )


def _render_tools(tools: Optional[List[Any]]) -> str:
    """把工具 schema 列表渲染为 LLM 可读文本（紧凑版，降低 prompt tokens）。

    只保留：名称 + 截断描述 + 参数名:类型(必填标记)。完整 JSON Schema 不再
    进 prompt——必填参数信息足够 LLM 选参，可选参数缺省由工具默认值兜底。
    """
    if not tools:
        return "（无可用工具）"
    lines = []
    for t in tools:
        desc = (t.description or "").strip().replace("\n", " ")
        if len(desc) > 48:
            desc = desc[:48].rstrip() + "…"
        params = t.parameters or {}
        props = params.get("properties") or {}
        required = set(params.get("required") or [])
        brief = []
        for name, meta in props.items():
            if not isinstance(meta, dict):
                meta = {}
            typ = meta.get("type", "any")
            mark = "*" if name in required else ""
            brief.append(f"{name}:{typ}{mark}")
        brief_s = " ".join(brief) if brief else "无参数"
        lines.append(f"- {t.name}: {desc}\n  参数: {brief_s}")
    return "\n".join(lines)


# ---------------- 规则直配（性能优化：零 LLM 调用的确定性规划） ----------------
_EXPR_RE = re.compile(r"^[\d\s+\-*/().]+$")


def _fast_plan_for(query: str) -> Optional[Plan]:
    """对确定性请求直接产出规划（calc / time），不适用返回 None。

    覆盖形态（保守，抽取失败一律回退 LLM 规划）：
      - 纯计算：`(3+5)*2`、`请计算 2**10`、`帮我算 100/4`、`2**10等于多少`
      - 纯时间：`现在几点`、`当前时间`、`今天日期`
    边界：表达式含函数调用/变量名等无法用正则覆盖 → 走 LLM。
    """
    q = (query or "").strip().strip("？?。，,！! ")
    if not q:
        return None

    # 1) 时间直配
    if re.search(r"(现在|当前|今天|此刻).*(几点|时间|日期)|(几点|时间|日期).*(现在|当前|今天)?$", q):
        return Plan(query=query, steps=[
            Step(step_id=1, action="time", args={}, thought="规则直配：时间查询"),
            Step(step_id=2, action="respond", args={}, thought="总结"),
        ])

    # 2) 天气直配：清洗前缀/时间词/尾部天气短语后，剩余整体即为城市名
    wq = q
    wq = re.sub(
        r"^(请|帮我|麻烦|给我)?(帮我查一下|帮我查|查一下|查询|查|看看)\s*", "", wq
    )
    wq = re.sub(r"(今天|现在|当前|实时|最新)", "", wq)
    wq = re.sub(
        r"(天气怎么样|天气如何|冷不冷|热不热|天气|气温|温度|怎么样|如何)$", "", wq
    )
    wq = wq.replace("的", "").strip()
    weather_keywords = ("天气", "气温", "温度", "冷不冷", "热不热", "预报")
    if any(k in q for k in weather_keywords) and re.fullmatch(
        r"[\u4e00-\u9fa5]{2,4}(?:市|区|县)?", wq
    ):
        return Plan(query=query, steps=[
            Step(step_id=1, action="weather", args={"city": wq}, thought="规则直配：天气查询"),
            Step(step_id=2, action="respond", args={}, thought="总结"),
        ])


    # 3) 计算直配：剥掉常见前缀后缀，再校验纯表达式
    expr = q
    expr = re.sub(r"^(请|帮我|给我|麻烦)?(计算|帮我算一下|帮我算|算算|算一下|算)\s*", "", expr)
    expr = re.sub(r"(等于多少|是多少|等于几|结果是多少|为多少)$", "", expr).strip()
    if expr and _EXPR_RE.match(expr) and any(op in expr for op in "+-*/"):
        return Plan(query=query, steps=[
            Step(step_id=1, action="calc", args={"expression": expr}, thought="规则直配：纯计算"),
            Step(step_id=2, action="respond", args={}, thought="总结"),
        ])

    # 5) 知识库检索直配："X是什么？请检索知识库回答" / "检索知识库：X"
    kbq = None
    m_suffix = re.match(
        r"^(.+?)[？?，,]?(请|帮我)?(检索|查询)(一下)?(知识库|内置知识库)(回答|解答)?$",
        q,
    )
    if m_suffix:
        kbq = (m_suffix.group(1) or "").strip()
    else:
        m_colon = re.match(
            r"^(请|帮我|麻烦)?(检索|查询|查)(一下)?(知识库|内置知识库)[：:,，]\s*(.+)$",
            q,
        )
        if m_colon:
            kbq = (m_colon.group(5) or "").strip()
    if kbq and 2 <= len(kbq) <= 40:
        return Plan(query=query, steps=[
            Step(step_id=1, action="kb_search", args={"query": kbq}, thought="规则直配：知识库检索"),
            Step(step_id=2, action="respond", args={}, thought="总结"),
        ])

    # 4) 复合任务直配："先查X天气，再算Y" / "先查X天气，然后现在几点" 等确定性组合。
    #    任一子句拆解失败 → 回退 LLM 规划（保持保守）。
    for sep in ("再", "然后", "接着"):
        if sep in q:
            part_a, _, part_b = q.partition(sep)
            pa = _extract_weather_city(part_a)
            pb = _extract_calc_expr(part_b)
            if pa and pb:
                return Plan(query=query, steps=[
                    Step(step_id=1, action="weather", args={"city": pa}, thought="规则直配：复合任务"),
                    Step(step_id=2, action="calc", args={"expression": pb}, thought="规则直配：复合任务"),
                    Step(step_id=3, action="respond", args={}, thought="总结"),
                ])
            ta = _extract_time_query(part_a)
            if ta and pb:
                return Plan(query=query, steps=[
                    Step(step_id=1, action="time", args={}, thought="规则直配：复合任务"),
                    Step(step_id=2, action="calc", args={"expression": pb}, thought="规则直配：复合任务"),
                    Step(step_id=3, action="respond", args={}, thought="总结"),
                ])
            break

    return None


def _extract_weather_city(text: str) -> Optional[str]:
    """从子句中提取城市名（复用天气清洗逻辑），失败返回 None。"""
    w = re.sub(r"^(先|请先)?(请|帮我|麻烦|给我)?(帮我查一下|帮我查|查一下|查询|查|看看)\s*", "", text)
    w = re.sub(r"[，,;；\s]", "", w)
    w = re.sub(r"(今天|现在|当前|实时|最新)", "", w)
    w = re.sub(r"(天气怎么样|天气如何|冷不冷|热不热|天气|气温|温度|怎么样|如何)$", "", w)
    w = w.replace("的", "").strip()
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}(?:市|区|县)?", w):
        return w
    return None


def _extract_calc_expr(text: str) -> Optional[str]:
    """从子句中提取纯表达式，失败返回 None。"""
    e = re.sub(r"^(再|然后|接着)?(请|帮我|给我|麻烦)?(计算|帮我算一下|帮我算|算算|算一下|算)\s*", "", text)
    e = e.strip()
    if e and _EXPR_RE.match(e) and any(op in e for op in "+-*/"):
        return e
    return None


def _extract_time_query(text: str) -> bool:
    """子句是否为时间查询。"""
    return bool(re.search(r"(现在|当前|今天|此刻).*(几点|时间|日期)|(几点|时间|日期).*(现在|当前|今天)?$", text))
