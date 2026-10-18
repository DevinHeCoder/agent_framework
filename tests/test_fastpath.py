"""性能优化专项测试：确定性工具直答 / 多工具并行执行 / 历史窗口截断。

- 直答：单工具（calc/time/weather）成功时跳过第二次 LLM 调用（llm.calls == 1）；
- 并行：多工具步骤并发执行，trace 仍按 step_id 排序；
- 窗口：最终回答只携带最近 _HISTORY_WINDOW 条历史。
"""
from src.agent.policy import RetryPolicy
from src.agent.react_agent import ReactAgent
from src.llm_client.fake import FakeLLMClient
from src.memory.in_memory_memory import InMemoryMemory
from src.planner.llm_planner import LLMPlanner
from src.tool import build_tool_registry

PLAN_CALC = (
    '{"steps": [{"action": "calc", "args": {"expression": "(3+5)*2"}, "thought": "算"},'
    '{"action": "respond", "args": {}, "thought": "答"}]}'
)
PLAN_TIME = (
    '{"steps": [{"action": "time", "args": {}, "thought": "取时间"},'
    '{"action": "respond", "args": {}, "thought": "答"}]}'
)
PLAN_WEATHER = (
    '{"steps": [{"action": "weather", "args": {"city": "杭州"}, "thought": "查天气"},'
    '{"action": "respond", "args": {}, "thought": "答"}]}'
)
PLAN_TWO_TOOLS = (
    '{"steps": [{"action": "calc", "args": {"expression": "2**10"}, "thought": "算"},'
    '{"action": "time", "args": {}, "thought": "取时间"},'
    '{"action": "respond", "args": {}, "thought": "汇总"}]}'
)


def make_responder(plan_jsons, answer="最终回答"):
    queue = list(plan_jsons)

    def responder(messages, kwargs):
        sys_prompt = messages[0].content if messages else ""
        if "任务规划器" in sys_prompt:
            return queue.pop(0) if queue else '{"steps": [{"action": "respond", "args": {}}]}'
        return answer

    return responder


def make_agent(plan_jsons, *, answer="最终回答", direct_answer=True):
    llm = FakeLLMClient(responder=make_responder(plan_jsons, answer=answer))
    agent = ReactAgent(
        llm=llm,
        planner=LLMPlanner(llm=llm, max_steps=6, parse_retries=0),
        memory=InMemoryMemory(),
        tool_registry=build_tool_registry(),
        policy=RetryPolicy(max_retries=0, param_fix_attempts=0, backoff_base=0.01),
        max_loop=5,
        direct_answer=direct_answer,
    )
    return agent, llm


# ---------------- 直答 ----------------
def test_direct_answer_calc_skips_second_llm():
    agent, llm = make_agent([PLAN_CALC])
    r = agent.run("算一下 (3+5)*2 的值是多少", session_id="d1")
    assert r.success is True
    assert r.answer == "计算结果：(3+5)*2 = 16"
    assert len(llm.calls) == 1  # 只有规划调用


def test_rule_time_zero_llm():
    agent, llm = make_agent([PLAN_TIME])
    r = agent.run("现在几点", session_id="d2")
    assert r.success is True
    assert r.answer.startswith("当前时间：")
    assert len(llm.calls) == 0


def test_direct_answer_weather():
    agent, llm = make_agent([PLAN_WEATHER])
    r = agent.run("帮我看看杭州今天的天气情况", session_id="d3")
    assert r.success is True
    assert "杭州" in r.answer and "°C" in r.answer
    assert len(llm.calls) == 1


def test_direct_answer_disabled_uses_llm():
    agent, llm = make_agent([PLAN_CALC], answer="结果是 16", direct_answer=False)
    r = agent.run("算一下 (3+5)*2 的值是多少", session_id="d4")
    assert r.success is True
    assert r.answer == "结果是 16"
    assert len(llm.calls) == 2  # 规划 + 最终回答


# ---------------- 并行执行 ----------------
def test_multi_tool_parallel_execution():
    agent, llm = make_agent([PLAN_TWO_TOOLS], answer="汇总完成")
    r = agent.run("算 2**10 和现在时刻", session_id="d5")
    assert r.success is True
    # 全部确定性工具成功 → 拼接直答，跳过回答 LLM
    assert r.answer.startswith("计算结果：2**10 = 1024；当前时间：")
    assert len(llm.calls) == 1  # 只有规划调用
    # trace 按 step_id 排序，两条工具步骤均成功
    actions = [(t.action, t.status) for t in r.trace]
    assert actions[0] == ("calc", "success")
    assert actions[1] == ("time", "success")
    assert len(r.trace) == 3  # calc + time + respond
    assert r.steps_taken == 3
    assert "1024" in r.trace[0].observation


# ---------------- 历史窗口截断 ----------------
def test_history_window_truncation():
    # 9 轮对话：第 9 轮开始时 memory 有 16 条历史；最终回答只携带最近 10 条
    # （丢最早 6 条 = 第 0~2 轮，第 3 轮起保留）
    agent, llm = make_agent([PLAN_CALC] * 9, answer="ok", direct_answer=False)
    for i in range(9):
        agent.run(f"第{i}轮", session_id="d6")
    final_call = llm.calls[-1]
    joined = " ".join(m.content for m in final_call[0])
    assert "第8轮" in joined          # 最近历史在
    assert "第3轮" in joined          # 窗口起点保留
    assert "第2轮" not in joined      # 最早历史被窗口截断
    assert "第0轮" not in joined


# ---------------- 规划快模型透传 ----------------
def test_planner_plan_model_passthrough():
    from src.planner.llm_planner import LLMPlanner

    llm = FakeLLMClient(responder=make_responder([PLAN_CALC]))
    planner = LLMPlanner(llm=llm, max_steps=6, parse_retries=0, plan_model="qwen3.8-flash")
    planner.plan("帮我算一下", tools=[])
    # 规划调用带上了快模型；无 plan_model 时不带（回退默认）
    assert llm.calls[0][1].get("model") == "qwen3.8-flash"

    llm2 = FakeLLMClient(responder=make_responder([PLAN_CALC]))
    planner2 = LLMPlanner(llm=llm2, max_steps=6, parse_retries=0)
    planner2.plan("帮我算一下", tools=[])
    assert llm2.calls[0][1].get("model") is None


# ---------------- 规则直配（零 LLM 调用） ----------------
def test_rule_calc_zero_llm():
    agent, llm = make_agent([PLAN_CALC], answer="不应被调用")
    r = agent.run("请计算 (3+5)*2", session_id="d7")
    assert r.success is True
    assert r.answer == "计算结果：(3+5)*2 = 16"
    assert len(llm.calls) == 0
    assert r.trace[0].action == "calc"


def test_rule_calc_with_suffix():
    agent, llm = make_agent([PLAN_CALC], answer="不应被调用")
    r = agent.run("2**10等于多少", session_id="d8")
    assert r.success is True
    assert "1024" in r.answer
    assert len(llm.calls) == 0


def test_rule_not_match_falls_back_to_llm():
    plan_json = ('{"steps": [{"action": "calc", "args": {"expression": "abs(-8)"}, '
                 '"thought": "算"}, {"action": "respond", "args": {}}]}')
    agent, llm = make_agent([plan_json], answer="结果是 8")
    r = agent.run("帮我算一下 abs(-8) 等于多少", session_id="d9")
    assert r.success is True
    assert "8" in r.answer
    assert len(llm.calls) == 1  # 含函数调用 → 回退 LLM 规划


def test_rule_weather_city_extraction():
    agent, llm = make_agent([], answer="不应被调用")
    r = agent.run("帮我查一下杭州今天的天气", session_id="d10")
    assert r.success is True
    assert "杭州" in r.answer
    assert len(llm.calls) == 0  # 规则直配：零 LLM 调用
    assert r.trace[0].action == "weather"
    assert r.trace[0].args == {"city": "杭州"}


def test_rule_time_not_eaten_by_weather():
    agent, llm = make_agent([], answer="不应被调用")
    r = agent.run("现在几点", session_id="d11")
    assert r.success is True
    assert len(llm.calls) == 0
    assert r.trace[0].action == "time"


# ---------------- 复合任务（先X再Y）规则直配 ----------------
def test_compound_rule_weather_calc():
    agent, llm = make_agent([], answer="不应被调用")
    r = agent.run("先查一下北京天气，再帮我算一下2**10", session_id="d12")
    assert r.success is True
    assert "北京天气" in r.answer and "2**10 = 1024" in r.answer
    assert len(llm.calls) == 0  # 规则直配 + 多工具直答：零 LLM
    actions = [(t.action, t.status) for t in r.trace]
    assert actions[0] == ("weather", "success")
    assert actions[1] == ("calc", "success")
    assert r.trace[0].args == {"city": "北京"}
    assert r.trace[1].args == {"expression": "2**10"}


def test_multi_direct_answer_with_kb():
    # kb_search 进直答白名单：kb+calc 全部成功 → 拼接直答，跳过回答 LLM
    kb_plan = (
        '{"steps": [{"action": "kb_search", "args": {"query": "双缓存记忆"}, "thought": "检索"},'
        '{"action": "calc", "args": {"expression": "1+1"}, "thought": "算"},'
        '{"action": "respond", "args": {}, "thought": "汇总"}]}'
    )
    agent, llm = make_agent([kb_plan], answer="知识库总结")
    r = agent.run("帮我检索知识库并算 1+1", session_id="d13")
    assert r.success is True
    assert "知识库检索结果" in r.answer
    assert "计算结果：1+1 = 2" in r.answer
    assert len(llm.calls) == 1  # 只有规划调用


def test_rule_kb_search_zero_llm():
    # "X是什么？请检索知识库回答" → 规则直配 kb_search，零 LLM
    agent, llm = make_agent([], answer="不应被调用")
    r = agent.run("双缓存记忆机制是什么？请检索知识库回答", session_id="d14")
    assert r.success is True
    assert "知识库检索结果" in r.answer
    assert "双缓存记忆" in r.answer
    assert len(llm.calls) == 0
    assert r.trace[0].action == "kb_search"
    assert r.trace[0].args == {"query": "双缓存记忆机制是什么"}
