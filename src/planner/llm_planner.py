"""LLM 规划器：让 LLM 做任务拆解、多步骤规划、自动选择工具（需求②核心）。

流程：
1. 把用户请求 + 可用工具 schema 组装进 system prompt；
2. 要求 LLM 只输出 JSON：{"steps": [{"action", "args", "thought"}, ...]}；
3. 用 json_parser 容错解析；输出非法时带错误重试（parse_retries）；
4. 校验步骤结构、按 max_steps 截断、自动补 respond 收尾步骤。

与 fake LLM 搭配可离线跑通全链路；与真实 LLM 搭配即真实拆解。
"""
import json
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
2. 用户请求可直接回答时，只输出一个 respond 步骤。
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
        logger=None,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.parse_retries = parse_retries
        self.system_prompt_template = system_prompt_template
        self._logger = logger

    def plan(
        self,
        query: str,
        tools: Optional[List[Any]] = None,
        context: Optional[List[Any]] = None,
    ) -> Plan:
        messages = [
            ChatMessage(
                role="system",
                content=self.system_prompt_template.format(
                    max_steps=self.max_steps,
                    tools_desc=_render_tools(tools),
                ),
            ),
            ChatMessage(role="user", content=f"用户请求：{query}"),
        ]

        last_error: Optional[Exception] = None
        for attempt in range(self.parse_retries + 1):
            raw = self.llm.chat(messages, temperature=0.0)
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


def _render_tools(tools: Optional[List[Any]]) -> str:
    """把工具 schema 列表渲染为 LLM 可读文本。"""
    if not tools:
        return "（无可用工具）"
    lines = []
    for t in tools:
        try:
            params = json.dumps(t.parameters, ensure_ascii=False)
        except (TypeError, AttributeError):
            params = "{}"
        lines.append(f"- {t.name}: {t.description}\n  参数: {params}")
    return "\n".join(lines)
