"""P1 工具层单测：注册中心、参数校验、四工具执行、安全计算器、未注册兜底。"""
import pytest

from src.common.exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolParamError,
)
from src.tool import build_tool_registry, run_tool
from src.tool.base import ToolResult
from src.tool.validator import validate_args


@pytest.fixture()
def reg():
    return build_tool_registry()


# ---------------- 注册中心 ----------------
def test_registry_has_all_tools(reg):
    for name in ("calc", "time", "weather", "kb_search"):
        assert reg.has(name), f"工具 {name} 应已注册"


def test_build_tool_registry_enabled_validation():
    with pytest.raises(ToolNotFoundError):
        build_tool_registry(enabled=["calc", "no_such_tool"])


def test_run_tool_not_found(reg):
    with pytest.raises(ToolNotFoundError):
        run_tool(reg, "no_such_tool", {})


# ---------------- calc 计算器 ----------------
def test_calc_basic(reg):
    r = run_tool(reg, "calc", {"expression": "(3+5)*2"})
    assert isinstance(r, ToolResult) and r.ok
    assert r.data["result"] == 16


def test_calc_power_and_abs(reg):
    assert run_tool(reg, "calc", {"expression": "2**10"}).data["result"] == 1024
    assert run_tool(reg, "calc", {"expression": "abs(-8)"}).data["result"] == 8
    assert run_tool(reg, "calc", {"expression": "7 // 2"}).data["result"] == 3


def test_calc_rejects_dangerous_expression(reg):
    with pytest.raises(ToolExecutionError):
        run_tool(reg, "calc", {"expression": "__import__('os')"})
    with pytest.raises(ToolExecutionError):
        run_tool(reg, "calc", {"expression": "[1,2,3]"})
    with pytest.raises(ToolExecutionError):
        run_tool(reg, "calc", {"expression": "1/0"})


def test_calc_missing_required_param(reg):
    with pytest.raises(ToolParamError):
        run_tool(reg, "calc", {})
    with pytest.raises(ToolParamError):
        run_tool(reg, "calc", {"expression": 123})  # 类型错误


# ---------------- time 时间 ----------------
def test_time_default(reg):
    r = run_tool(reg, "time", {})
    assert r.ok and isinstance(r.data["datetime"], str)
    assert isinstance(r.data["timestamp"], int)


def test_time_custom_format(reg):
    r = run_tool(reg, "time", {"format": "%Y"})
    assert len(r.data["datetime"]) == 4


# ---------------- weather 天气 ----------------
def test_weather_known_city(reg):
    r = run_tool(reg, "weather", {"city": "北京"})
    assert r.ok
    assert r.data["city"] == "北京"
    assert r.data["temperature"] == 24
    assert r.data["source"] == "mock"


def test_weather_unknown_city(reg):
    r = run_tool(reg, "weather", {"city": "火星"})
    assert r.ok and "note" in r.data


def test_weather_missing_city(reg):
    with pytest.raises(ToolParamError):
        run_tool(reg, "weather", {})


# ---------------- kb_search 检索 ----------------
def test_kb_search_hits(reg):
    r = run_tool(reg, "kb_search", {"query": "工具注册中心"})
    assert r.ok
    assert r.data["source"] == "mock"
    assert len(r.data["results"]) > 0
    assert all("doc_id" in x and "content" in x for x in r.data["results"])


def test_kb_search_top_k(reg):
    r = run_tool(reg, "kb_search", {"query": "agent 记忆 重试 规划", "top_k": 3})
    assert len(r.data["results"]) <= 3


def test_kb_search_top_k_out_of_range(reg):
    with pytest.raises(ToolParamError):
        run_tool(reg, "kb_search", {"query": "x", "top_k": 99})


# ---------------- ToolResult 渲染 ----------------
def test_tool_result_content_readable(reg):
    r = run_tool(reg, "calc", {"expression": "1+1"})
    assert r.content  # 非空可读文本
    assert "2" in r.content


# ---------------- validator 独立单测 ----------------
def test_validator_required_and_default():
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "integer"}, "b": {"type": "string", "default": "x"}},
    }
    assert validate_args(schema, {"a": 1}) == {"a": 1, "b": "x"}
    with pytest.raises(ToolParamError):
        validate_args(schema, {})
    with pytest.raises(ToolParamError):
        validate_args(schema, {"a": "not-int"})


def test_validator_enum_and_range():
    schema = {
        "type": "object",
        "required": ["level", "size"],
        "properties": {
            "level": {"type": "integer", "enum": [1, 2, 3]},
            "size": {"type": "integer", "minimum": 1, "maximum": 10},
        },
    }
    assert validate_args(schema, {"level": 2, "size": 5}) == {"level": 2, "size": 5}
    with pytest.raises(ToolParamError):
        validate_args(schema, {"level": 9, "size": 5})
    with pytest.raises(ToolParamError):
        validate_args(schema, {"level": 2, "size": 99})


def test_validator_string_length():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "min_length": 2, "max_length": 5}},
    }
    assert validate_args(schema, {"name": "abc"}) == {"name": "abc"}
    with pytest.raises(ToolParamError):
        validate_args(schema, {"name": "a"})
    with pytest.raises(ToolParamError):
        validate_args(schema, {"name": "abcdef"})


def test_validator_number_accepts_int_and_float():
    schema = {"type": "object", "properties": {"v": {"type": "number"}}}
    assert validate_args(schema, {"v": 1})["v"] == 1
    assert validate_args(schema, {"v": 1.5})["v"] == 1.5
