"""
ReactAgent：ReAct 风格的任务执行器（需求②⑤的落地核心）。

执行循环（plan-then-execute）:
1. 读取会话记忆 → 交给 Planner 拆解任务（LLM 自动选工具）；
2. 逐步骤执行：
   - action=工具 → 参数校验失败回喂 LLM 自愈（param_fix_attempts）、
     执行失败指数退避重试（max_retries）、仍失败记录 trace 并继续；
   - action=respond 或步骤耗尽 → 结合工具观察结果让 LLM 生成最终回答；
3. 整轮失败 → RetryPolicy.build_fallback() 兜底；
4. 用户请求与最终回答写回记忆（多轮连续任务的记忆来源）。
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from src.agent.base import AgentResult, BaseAgent, TraceEntry
from src.agent.policy import RetryPolicy
from src.agent.registry import agent_registry
from src.common.exceptions import (
    LLMError,
    PlannerError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolParamError,
)
from src.common.security import redact_secrets
from src.llm_client.base import ChatMessage, LLMClient
from src.memory.base import BaseMemory, Message
from src.planner.base import BasePlanner, Plan, Step
from src.tool import list_tool_schemas
from src.utils.json_parser import try_parse_json_strict

logger = logging.getLogger(__name__)

_SELF_HEAL_SYSTEM_PROMPT = (
    "你是参数修正器。工具参数校验失败，请根据错误信息修正参数，"
    "只输出修正后的参数 JSON（一个对象），禁止输出其他文字。"
)

_FINAL_SYSTEM_PROMPT = (
    "你是智能助手。请基于工具观察结果，用中文直接回答用户请求；"
    "若无工具结果则凭自身知识回答。不要提到内部步骤。"
)

# 直答白名单：结果确定性强、无需 LLM 润色的工具（跳过第二次 LLM 调用）。
# kb_search 检索片段本身就是答案载体，直接呈现引用式结果，不再二次润色。
_DIRECT_ANSWER_TOOLS = ("calc", "time", "weather", "kb_search")

# 最终回答只携带最近 N 条历史（避免多轮后 prompt 无限膨胀拖慢响应）
_HISTORY_WINDOW = 10


@agent_registry.register("react")
class ReactAgent(BaseAgent):
    """ReAct 风格任务执行器。"""

    def __init__(
        self,
        llm: LLMClient,
        planner: BasePlanner,
        memory: BaseMemory,
        tool_registry,
        policy: Optional[RetryPolicy] = None,
        max_loop: int = 5,
        json_parse_retries: int = 2,
        enabled_tools: Optional[List[str]] = None,
        direct_answer: bool = True,
    ) -> None:
        self.llm = llm
        self.planner = planner
        self.memory = memory
        self.tool_registry = tool_registry
        self.policy = policy or RetryPolicy()
        self.max_loop = max_loop
        self.json_parse_retries = json_parse_retries
        self.enabled_tools = enabled_tools
        # 性能优化：确定性工具（calc/time/weather）单步成功时直答，跳过第二次 LLM 调用
        self.direct_answer = direct_answer

    # ---------------- 主入口 ----------------
    def run(self, query: str, session_id: str = "default") -> AgentResult:
        started = time.monotonic()
        history = self.memory.get_messages(session_id)
        tool_schemas = list_tool_schemas(self.tool_registry, self.enabled_tools)

        try:
            plan = self.planner.plan(query, tools=tool_schemas, context=history)
        except (PlannerError, LLMError) as e:
            # LLM 未配置/网络异常也走兜底：不让规划失败直接 500
            logger.warning("plan 失败: %s", e)
            return AgentResult(query, self.policy.build_fallback(e), False, 0, [])

        bounded = plan.steps[: self.max_loop]
        tool_steps = [s for s in bounded if s.action != "respond"]
        has_respond = any(s.action == "respond" for s in bounded)
        respond_thought = (
            bounded[-1].thought
            if bounded and bounded[-1].action == "respond"
            else ""
        )

        trace: List[TraceEntry] = []
        observations: List[str] = []
        outcomes: Dict[int, dict] = {}
        success = True

        # 性能优化：独立工具步骤并行执行（步骤间无数据依赖，结果按 step_id 排序）
        if tool_steps:
            with ThreadPoolExecutor(
                max_workers=min(len(tool_steps), 4)
            ) as pool:
                futures = {
                    pool.submit(self._execute_step, step): step
                    for step in tool_steps
                }
                for fut in as_completed(futures):
                    step = futures[fut]
                    try:
                        outcome = fut.result()
                    except ToolError as e:
                        outcome = {
                            "status": "failed",
                            "observation": f"步骤失败（{step.action}）：{e}",
                            "result": None,
                            "duration_ms": 0.0,
                        }
                        logger.warning("步骤 %s 失败: %s", step.action, e)
                    outcomes[step.step_id] = outcome

        for step in sorted(tool_steps, key=lambda s: s.step_id):
            out = outcomes.get(step.step_id, {
                "status": "failed", "observation": "步骤未执行", "result": None, "duration_ms": 0.0,
            })
            observation = out["observation"]
            if out["status"] == "success":
                trace.append(
                    TraceEntry(step.step_id, step.action, step.args, observation, "success")
                )
            else:
                success = False
                trace.append(
                    TraceEntry(step.step_id, step.action, step.args, observation, "failed")
                )
            observations.append(observation)
            logger.info(
                "tool_step session_id=%s step_id=%s action=%s status=%s "
                "duration_ms=%.1f args_summary=%s",
                session_id, step.step_id, step.action, out["status"],
                out.get("duration_ms", 0.0),
                redact_secrets(json.dumps(step.args, ensure_ascii=False)[:200]),
                extra={"session_id": session_id, "step_id": step.step_id,
                       "action": step.action, "status": out["status"],
                       "duration_ms": round(out.get("duration_ms", 0.0), 1),
                       "args_summary": redact_secrets(json.dumps(step.args, ensure_ascii=False)[:200])},
            )

        steps_taken = len(tool_steps) + (1 if has_respond else 0)
        answer = ""

        if has_respond:
            # 性能优化：全部工具均为确定性工具且全部成功 → 拼接直答，跳过第二次 LLM
            direct = None
            if self.direct_answer:
                direct = self._direct_answer_for_multi(tool_steps, outcomes)
            if direct:
                answer = direct
            else:
                answer = self._final_answer(query, history, observations, respond_thought)
            trace.append(
                TraceEntry(len(tool_steps) + 1, "respond", {}, answer, "success")
            )
        elif observations:
            # 无 respond 步骤且循环自然结束 → 综合观察结果生成回答
            answer = self._final_answer(query, history, observations, "")

        if not answer:
            success = False
            answer = self.policy.build_fallback(
                "任务执行未产生有效结果" if not trace else trace[-1].observation
            )

        # 写回记忆（多轮连续任务）
        self.memory.add_message(session_id, Message(role="user", content=query))
        self.memory.add_message(session_id, Message(role="assistant", content=answer))

        logger.info(
            "agent_run session_id=%s steps=%s success=%s duration_ms=%.1f",
            session_id, steps_taken, success,
            (time.monotonic() - started) * 1000,
            extra={"session_id": session_id, "duration_ms": round((time.monotonic() - started) * 1000, 1)},
        )
        return AgentResult(query, answer, success, steps_taken, trace)

    def _execute_step(self, step: Step) -> dict:
        """并行 worker：执行一个工具步骤（含自愈与重试），返回统一结果。"""
        started = time.monotonic()
        result = self._execute_tool(step)
        return {
            "status": "success",
            "observation": result.content,
            "result": result,
            "duration_ms": (time.monotonic() - started) * 1000,
        }

    def _direct_answer_for_multi(
        self, steps: List[Step], outcomes: Dict[int, dict]
    ) -> Optional[str]:
        """多工具直答：所有步骤都在确定性白名单且全部成功 → 拼接各步直答文本。

        任一步骤失败或为非确定性工具（如 kb_search 需要 LLM 综合）→ 回退 LLM。
        """
        if not steps:
            return None
        texts = []
        for s in steps:
            out = outcomes.get(s.step_id, {})
            if out.get("status") != "success" or out.get("result") is None:
                return None
            t = self._direct_answer_for(s.action, out["result"])
            if t is None:
                return None
            texts.append(t)
        return "；".join(texts)

    def _direct_answer_for(self, action: str, result) -> Optional[str]:
        """确定性工具直答：返回可直接呈现的文本；不适用返回 None。

        仅对结果确定、无需 LLM 润色的工具生效（calc / time / weather）。
        """
        if action not in _DIRECT_ANSWER_TOOLS:
            return None
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return None
        try:
            if action == "calc":
                return f"计算结果：{data.get('expression')} = {data.get('result')}"
            if action == "time":
                return f"当前时间：{data.get('datetime')}"
            if action == "weather":
                if data.get("temperature") is None:
                    return f"{data.get('city', '')}：{data.get('note', '暂无数据')}"
                return (
                    f"{data.get('city')}天气：{data.get('temperature')}°C，"
                    f"{data.get('condition')}，湿度 {data.get('humidity')}%"
                )
            if action == "kb_search":
                results = data.get("results") or []
                if not results:
                    return f"知识库检索结果：未找到相关文档（{data.get('source', '')}）"
                lines = [
                    f"- [{r.get('title', '')}] {r.get('content', '')}"
                    f"（doc_id={r.get('doc_id', '')}）"
                    for r in results
                ]
                return "知识库检索结果：\n" + "\n".join(lines)
        except Exception:  # noqa: BLE001 - 直答失败回退 LLM
            return None
        return None

    # ---------------- 工具执行（含容错） ----------------
    def _execute_tool(self, step: Step):
        """执行一个工具步骤：参数自愈循环 + 执行重试。"""
        args = dict(step.args)
        last_error: Optional[Exception] = None

        for fix in range(self.policy.param_fix_attempts + 1):
            try:
                return self._run_with_retry(step, args)
            except ToolParamError as e:
                last_error = e
                if fix < self.policy.param_fix_attempts:
                    fixed = self._self_heal_args(step, args, e)
                    if fixed is None:
                        break
                    args = fixed
                else:
                    raise
        raise last_error  # type: ignore[misc]

    def _run_with_retry(self, step: Step, args: Dict[str, Any]):
        """带指数退避重试的工具调用（仅 ToolExecutionError 重试）。"""
        last_error: Optional[Exception] = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                return self._call_tool(step.action, args)
            except ToolExecutionError as e:
                last_error = e
                if attempt < self.policy.max_retries:
                    self.policy.sleep(attempt)
        raise last_error  # type: ignore[misc]

    def _call_tool(self, name: str, args: Dict[str, Any]):
        from src.tool import run_tool

        return run_tool(self.tool_registry, name, args)

    def _self_heal_args(self, step: Step, args: Dict[str, Any], error: Exception):
        """把校验错误回喂 LLM，返回修正后参数；LLM 输出非法时返回 None。"""
        if self.llm is None:
            return None
        schema = self._find_schema(step.action)
        payload = {
            "action": step.action,
            "schema": getattr(schema, "parameters", {}),
            "args": args,
            "error": str(error),
        }
        prompt = json.dumps(payload, ensure_ascii=False)
        try:
            raw = self.llm.chat(
                [
                    ChatMessage(role="system", content=_SELF_HEAL_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ],
                temperature=0.0,
            )
        except LLMError:
            return None
        obj = try_parse_json_strict(raw)
        return obj if isinstance(obj, dict) else None

    def _find_schema(self, name: str):
        for s in list_tool_schemas(self.tool_registry, self.enabled_tools):
            if s.name == name:
                return s
        return None

    # ---------------- 最终回答 ----------------
    def _final_answer(
        self,
        query: str,
        history: List[Message],
        observations: List[str],
        respond_thought: str,
    ) -> str:
        obs_text = "\n".join(observations) if observations else "（无工具结果）"
        user_content = f"用户请求：{query}\n工具观察结果：\n{obs_text}"
        if respond_thought:
            user_content += f"\n规划建议：{respond_thought}"

        messages = [ChatMessage(role="system", content=_FINAL_SYSTEM_PROMPT)]
        # 性能优化：只携带最近 N 条历史，避免多轮会话 prompt 无限膨胀
        messages += [
            ChatMessage(role=m.role, content=m.content)
            for m in history[-_HISTORY_WINDOW:]
        ]
        messages.append(ChatMessage(role="user", content=user_content))

        try:
            return self.llm.chat(messages, temperature=0.3)
        except LLMError as e:
            logger.warning("最终回答生成失败: %s", e)
            return ""
