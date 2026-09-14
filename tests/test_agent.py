"""P4 Agent 核心单测：端到端工具调度、参数自愈、执行重试、多轮记忆、失败兜底、policy 数学。"""
import pytest

from src.agent.base import AgentResult, TraceEntry
from src.agent.policy import RetryPolicy
from src.agent.react_agent import ReactAgent
from src.llm_client.fake import FakeLLMClient
from src.memory.base import Message
from src.memory.in_memory_memory import InMemoryMemory
from src.planner.llm_planner import LLMPlanner
from src.tool import build_tool_registry

PLAN_CALC = (
    '{"steps": [{"action": "calc", "args": {"expression": "(3+5)*2"}, "thought": "先计算"},'
    '{"action": "respond", "args": {}, "thought": "总结"}]}'
)
PLAN_WEATHER = '{"steps": [{"action": "weather", "args": {}}, {"action": "respond", "args": {}}]}'
PLAN_ZERODIV = '{"steps": [{"action": "calc", "args": {"expression": "1/0"}}]}'
PLAN_NO_TOOL = '{"steps": [{"action": "no_such_tool", "args": {}}]}'


def make_responder(plan_jsons, *, fixer=None, answer="最终回答"):
    queue = list(plan_jsons)

    def responder(messages, kwargs):
        sys_prompt = messages[0].content if messages else ""
        if "任务规划器" in sys_prompt:
            if queue:
                return queue.pop(0)
            return '{"steps": [{"action": "respond", "args": {}, "thought": "直接回答"}]}'
        if "参数修正器" in sys_prompt:
            return fixer(messages) if fixer else "{}"
        return answer

    return responder


def make_agent(
    *,
    plan_jsons,
    fixer=None,
    answer="最终回答",
    max_retries=0,
    param_fix_attempts=0,
    parse_retries=2,
    max_loop=5,
):
    reg = build_tool_registry()
    llm = FakeLLMClient(responder=make_responder(plan_jsons, fixer=fixer, answer=answer))
    planner = LLMPlanner(llm=llm, max_steps=6, parse_retries=parse_retries)
    mem = InMemoryMemory()
    policy = RetryPolicy(
        max_retries=max_retries,
        param_fix_attempts=param_fix_attempts,
        backoff_base=0.01,
    )
    agent = ReactAgent(
        llm=llm, planner=planner, memory=mem, tool_registry=reg,
        policy=policy, max_loop=max_loop,
    )
    return agent, llm, mem


# ---------------- 端到端：工具调度 ----------------
def test_agent_runs_tool_and_answers():
    agent, llm, mem = make_agent(plan_jsons=[PLAN_CALC], answer="结果是 16")
    result = agent.run("帮我算 (3+5)*2", session_id="s1")
    assert isinstance(result, AgentResult)
    assert result.success is True
    assert result.answer == "结果是 16"
    assert result.steps_taken == 2
    assert result.trace[0].status == "success"
    assert result.trace[0].action == "calc"
    assert "16" in result.trace[0].observation
    # 记忆已写入（user + assistant）
    assert [m.role for m in mem.get_messages("s1")] == ["user", "assistant"]


def test_agent_writes_multi_turn_memory():
    agent, llm, mem = make_agent(plan_jsons=[PLAN_CALC, PLAN_CALC], answer="16")
    agent.run("第一问", session_id="m")
    agent.run("第二问", session_id="m")
    msgs = mem.get_messages("m")
    assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]
    # 第二次最终回答应带上历史
    final_call = llm.calls[-1]
    joined = " ".join(m.content for m in final_call[0])
    assert "第一问" in joined and "第二问" in joined


# ---------------- 需求⑤：参数自动修正 ----------------
def test_agent_self_heals_params():
    # weather 缺 city → 校验失败 → LLM 修正为 {"city": "杭州"} → 执行成功
    fixer = lambda messages: '{"city": "杭州"}'  # noqa: E731
    agent, llm, mem = make_agent(
        plan_jsons=[PLAN_WEATHER],
        fixer=fixer,
        answer="杭州今天小雨",
        param_fix_attempts=2,
    )
    result = agent.run("杭州天气怎么样", session_id="s2")
    assert result.success is True
    assert result.trace[0].status == "success"
    assert "杭州" in result.trace[0].observation
    # 确认发生过一次参数修正调用
    heal_calls = [c for c in llm.calls if "参数修正器" in c[0][0].content]
    assert len(heal_calls) == 1


def test_agent_self_heal_fails_then_fallback():
    # LLM 修正输出非法（非 JSON）→ 自愈失败 → 步骤失败但流程不崩
    fixer = lambda messages: "不是JSON"  # noqa: E731
    agent, llm, mem = make_agent(
        plan_jsons=[PLAN_WEATHER],
        fixer=fixer,
        answer="兜底后仍回答",
        param_fix_attempts=1,
    )
    result = agent.run("杭州天气怎么样", session_id="s3")
    assert result.trace[0].status == "failed"
    assert result.success is False
    assert result.answer  # 有兜底/综合回答，不抛异常


# ---------------- 需求⑤：执行失败重试 ----------------
def test_agent_retries_then_continues(monkeypatch):
    sleeps = []

    def fake_sleep(self, attempt):
        sleeps.append(attempt)

    monkeypatch.setattr(RetryPolicy, "sleep", fake_sleep)
    agent, llm, mem = make_agent(
        plan_jsons=[PLAN_ZERODIV],
        answer="除法不可行",
        max_retries=2,
    )
    result = agent.run("算 1/0", session_id="s4")
    # 1/0 永远失败：重试 2 次 → 记录 failed → 无 respond → 综合回答
    assert sleeps == [0, 1]  # 两次退避
    assert result.trace[0].status == "failed"
    assert result.success is False
    assert result.answer == "除法不可行"


def test_agent_tool_not_found_fallback():
    agent, llm, mem = make_agent(plan_jsons=[PLAN_NO_TOOL], answer="没有这个工具")
    result = agent.run("调用不存在的工具", session_id="s5")
    assert result.trace[0].status == "failed"
    assert "no_such_tool" in result.trace[0].observation
    assert result.success is False


# ---------------- 需求⑤：规划失败兜底 ----------------
def test_agent_plan_failure_returns_fallback():
    # planner 解析彻底失败（parse_retries=0 + 非法输出）
    agent, llm, mem = make_agent(
        plan_jsons=["不是JSON"],
        parse_retries=0,
    )
    result = agent.run("触发规划失败", session_id="s6")
    assert result.success is False
    assert "抱歉" in result.answer


def test_agent_max_loop_cap():
    # 规划 10 步工具步骤，max_loop=3 → 只执行 3 步
    steps = ",".join(
        f'{{"action": "time", "args": {{}}, "thought": "t{i}"}}' for i in range(10)
    )
    agent, llm, mem = make_agent(
        plan_jsons=[f'{{"steps": [{steps}]}}'],
        answer="done",
        max_loop=3,
    )
    result = agent.run("循环任务", session_id="s7")
    assert result.steps_taken == 3
    assert len(result.trace) == 3


# ---------------- RetryPolicy 单测 ----------------
def test_policy_backoff_math():
    p = RetryPolicy(backoff_base=0.5, backoff_cap=8.0)
    assert p.backoff_seconds(0) == 0.5
    assert p.backoff_seconds(1) == 1.0
    assert p.backoff_seconds(2) == 2.0
    assert p.backoff_seconds(4) == 8.0  # 封顶
    assert p.backoff_seconds(10) == 8.0


def test_policy_fallback_text():
    p = RetryPolicy(fallback_text="抱歉，我暂时无法完成这个请求。")
    assert p.build_fallback() == "抱歉，我暂时无法完成这个请求。"
    assert "原因" in p.build_fallback("boom")


def test_trace_entry_dataclass():
    t = TraceEntry(step_id=1, action="calc", args={"expression": "1+1"}, observation="2")
    assert t.status == "success"
