"""P0 异常层级单测：继承关系、message/cause 属性、统一捕获。"""
import pytest

from src.common.exceptions import (
    AgentError,
    AgentFrameworkError,
    ConfigError,
    LLMError,
    MemoryError,
    PlannerError,
    RegistryError,
    RetryExhaustedError,
    SessionError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolParamError,
)


def test_exception_hierarchy():
    """所有层异常统一继承 AgentFrameworkError。"""
    for exc in (
        ConfigError,
        RegistryError,
        ToolError,
        MemoryError,
        LLMError,
        PlannerError,
        AgentError,
        SessionError,
    ):
        assert issubclass(exc, AgentFrameworkError)


def test_tool_exception_subclasses():
    assert issubclass(ToolNotFoundError, ToolError)
    assert issubclass(ToolParamError, ToolError)
    assert issubclass(ToolExecutionError, ToolError)
    assert issubclass(RetryExhaustedError, AgentError)


def test_message_and_cause():
    cause = ValueError("root cause")
    err = ConfigError("bad config", cause=cause)
    assert err.message == "bad config"
    assert err.cause is cause
    assert str(err) == "bad config"


def test_construct_without_message():
    err = RegistryError()
    assert err.message == ""
    assert err.cause is None


def test_unified_catch():
    """上层用 AgentFrameworkError 即可统一捕获任意层异常。"""
    with pytest.raises(AgentFrameworkError):
        raise ToolError("tool boom")
