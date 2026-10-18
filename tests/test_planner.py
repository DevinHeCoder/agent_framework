"""P4 规划层单测：LLM 任务拆解、JSON 容错解析、max_steps 截断、自动补 respond。"""
import pytest

from src.common.exceptions import PlannerError
from src.llm_client.fake import FakeLLMClient
from src.planner import build_planner
from src.planner.base import Plan, Step
from src.planner.llm_planner import LLMPlanner


def make_planner(responses, parse_retries=2, max_steps=6):
    llm = FakeLLMClient(responses=list(responses))
    return LLMPlanner(llm=llm, max_steps=max_steps, parse_retries=parse_retries)


def test_plan_parses_valid_steps():
    p = make_planner([
        '{"steps": [{"action": "calc", "args": {"expression": "(3+5)*2"}, "thought": "先计算"},'
        '{"action": "respond", "args": {}, "thought": "总结"}]}'
    ])
    plan = p.plan("帮我算 (3+5)*2 的值")
    assert isinstance(plan, Plan)
    assert len(plan.steps) == 2
    s1, s2 = plan.steps
    assert s1.action == "calc" and s1.args == {"expression": "(3+5)*2"}
    assert s1.thought == "先计算"
    assert s2.action == "respond"


def test_plan_auto_appends_respond():
    p = make_planner(['{"steps": [{"action": "weather", "args": {"city": "杭州"}}]}'])
    plan = p.plan("杭州天气")
    assert plan.steps[-1].action == "respond"


def test_plan_max_steps_truncated():
    raw = '{"steps": ' + str([
        {"action": "calc", "args": {"expression": f"1+{i}"}} for i in range(5)
    ]).replace("'", '"') + '}'
    p = make_planner([raw], max_steps=2)
    plan = p.plan("x")
    # 2 步 + 自动补 respond = 3
    assert len(plan.steps) == 3
    assert plan.steps[0].action == "calc"
    assert plan.steps[1].action == "calc"
    assert plan.steps[2].action == "respond"


def test_plan_invalid_json_retries_then_raises():
    p = make_planner(["不是JSON", "还是不是JSON", "依旧不是"], parse_retries=2)
    with pytest.raises(PlannerError):
        p.plan("x")


def test_plan_invalid_json_recovers_on_retry():
    # 第一次非法，第二次合法 → 重试后成功
    p = make_planner(
        ["垃圾文本", '{"steps": [{"action": "time", "args": {}}]}'],
        parse_retries=2,
    )
    plan = p.plan("x")
    assert plan.steps[0].action == "time"


def test_plan_missing_steps_raises():
    p = make_planner(['{"not_steps": 1}'])
    with pytest.raises(PlannerError):
        p.plan("x")


def test_plan_empty_steps_raises():
    p = make_planner(['{"steps": []}'])
    with pytest.raises(PlannerError):
        p.plan("x")


def test_plan_step_missing_action_raises():
    p = make_planner(['{"steps": [{"args": {}}]}'])
    with pytest.raises(PlannerError):
        p.plan("x")


def test_build_planner_default_and_options():
    llm = FakeLLMClient()
    p = build_planner({}, llm=llm)
    assert isinstance(p, LLMPlanner)
    assert p.max_steps == 6
    p2 = build_planner({"provider": "llm", "max_steps": 3}, llm=llm)
    assert p2.max_steps == 3


def test_planner_registry_typed():
    from src.planner.base import BasePlanner
    from src.planner.registry import planner_registry

    assert "llm" in planner_registry.names
    assert issubclass(planner_registry.get("llm"), BasePlanner)
