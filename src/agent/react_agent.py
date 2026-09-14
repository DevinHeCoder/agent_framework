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
    ) -> None:
        self.llm = llm
        self.planner = planner
        self.memory = memory
        self.tool_registry = tool_registry
        self.policy = policy or RetryPolicy()
        self.max_loop = max_loop
        self.json_parse_retries = json_parse_retries
        self.enabled_tools = enabled_tools

    # ---------------- 主入口 ----------------
    def run(self, query: str, session_id: str = "default") -> AgentResult:
        history = self.memory.get_messages(session_id)
        tool_schemas = list_tool_schemas(self.tool_registry, self.enabled_tools)

        try:
            plan = self.planner.plan(query, tools=tool_schemas, context=history)
        except PlannerError as e:
            logger.warning("plan 失败: %s", e)
            return AgentResult(query, self.policy.build_fallback(e), False, 0, [])

        trace: List[TraceEntry] = []
        observations: List[str] = []
        answer = ""
        steps_taken = 0
        success = True

        for step in plan.steps[: self.max_loop]:
            steps_taken += 1
            if step.action == "respond":
                answer = self._final_answer(query, history, observations, step.thought)
                trace.append(
                    TraceEntry(step.step_id, "respond", {}, answer, "success")
                )
                break

            try:
                result = self._execute_tool(step)
                observation = result.content
                trace.append(
                    TraceEntry(step.step_id, step.action, step.args, observation, "success")
                )
            except ToolError as e:
                success = False
                observation = f"步骤失败（{step.action}）：{e}"
                trace.append(
                    TraceEntry(step.step_id, step.action, step.args, observation, "failed")
                )
                logger.warning("步骤 %s 失败: %s", step.action, e)
            observations.append(observation)
        else:
            # 无 respond 步骤且循环自然结束 → 综合观察结果生成回答
            if observations:
                answer = self._final_answer(query, history, observations, "")

        if not answer:
            success = False
            answer = self.policy.build_fallback(
                "任务执行未产生有效结果" if not trace else trace[-1].observation
            )

        # 写回记忆（多轮连续任务）
        self.memory.add_message(session_id, Message(role="user", content=query))
        self.memory.add_message(session_id, Message(role="assistant", content=answer))

        return AgentResult(query, answer, success, steps_taken, trace)

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
        messages += [
            ChatMessage(role=m.role, content=m.content) for m in history
        ]
        messages.append(ChatMessage(role="user", content=user_content))

        try:
            return self.llm.chat(messages, temperature=0.3)
        except LLMError as e:
            logger.warning("最终回答生成失败: %s", e)
            return ""
