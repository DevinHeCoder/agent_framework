"""P3 LLM 客户端层单测：fake 可编程响应、openai_compatible 消息转换与异常包装、build_llm_client 选型。"""
import pytest

from src.common.exceptions import LLMError
from src.llm_client import build_llm_client
from src.llm_client.base import ChatMessage, LLMClient
from src.llm_client.fake import FakeLLMClient
from src.llm_client.openai_compatible import OpenAICompatibleClient


# ---------------- FakeOpenAIClient（模拟 openai SDK 响应结构） ----------------
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class FakeOpenAIClient:
    """模拟 openai 客户端：记录最近一次 create 参数，返回可配置内容。"""

    def __init__(self, content="你好"):
        self._content = content
        self.last_params = None

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **params):
            self._outer.last_params = params
            return _FakeResponse(self._outer._content)

    class _Chat:
        def __init__(self, outer):
            self.completions = FakeOpenAIClient._Completions(outer)

    @property
    def chat(self):
        return FakeOpenAIClient._Chat(self)

    def close(self):
        pass


def cm(role: str, content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


# ---------------- FakeLLMClient ----------------
def test_fake_queue_and_default():
    llm = FakeLLMClient(responses=["规划结果", "工具结果"], default_reply="兜底回复")
    assert llm.chat([cm("user", "q")]) == "规划结果"
    assert llm.chat([cm("user", "q")]) == "工具结果"
    assert llm.chat([cm("user", "q")]) == "兜底回复"


def test_fake_responder_overrides_queue():
    def responder(messages, kwargs):
        return f"echo:{messages[-1].content}"

    llm = FakeLLMClient(responses=["队列里的"], responder=responder)
    assert llm.chat([cm("user", "hi")]) == "echo:hi"


def test_fake_records_calls():
    llm = FakeLLMClient()
    llm.chat([cm("system", "你是助手"), cm("user", "你好")], temperature=0.2)
    assert len(llm.calls) == 1
    msgs, kwargs = llm.calls[0]
    assert [m.role for m in msgs] == ["system", "user"]
    assert kwargs == {"temperature": 0.2}


def test_fake_close():
    llm = FakeLLMClient()
    llm.chat([cm("user", "x")])
    llm.close()
    assert llm.calls == []


# ---------------- OpenAICompatibleClient（注入 FakeOpenAIClient） ----------------
def test_openai_compatible_payload_and_return():
    inner = FakeOpenAIClient(content="计算结果是 42")
    llm = OpenAICompatibleClient(client=inner, model="deepseek-chat", temperature=0.1)
    reply = llm.chat(
        [cm("system", "你是工具调度器"), cm("user", "帮我算 (3+5)*2")],
        max_tokens=128,
    )
    assert reply == "计算结果是 42"
    # 校验透传给 SDK 的参数形态
    assert inner.last_params["model"] == "deepseek-chat"
    assert inner.last_params["temperature"] == 0.1
    assert inner.last_params["messages"] == [
        {"role": "system", "content": "你是工具调度器"},
        {"role": "user", "content": "帮我算 (3+5)*2"},
    ]
    assert inner.last_params["max_tokens"] == 128


def test_openai_compatible_kwargs_override():
    inner = FakeOpenAIClient()
    llm = OpenAICompatibleClient(client=inner, model="m1", temperature=0.5)
    llm.chat([cm("user", "x")], model="m2", temperature=0.9)
    assert inner.last_params["model"] == "m2"
    assert inner.last_params["temperature"] == 0.9


def test_openai_compatible_empty_content_raises():
    inner = FakeOpenAIClient(content=None)
    llm = OpenAICompatibleClient(client=inner)
    with pytest.raises(LLMError):
        llm.chat([cm("user", "x")])


def test_openai_compatible_api_error_wrapped(monkeypatch):
    class BoomClient:
        class _C:
            def create(self, **kw):
                raise ConnectionError("network down")

        class _Chat:
            def __init__(self):
                self.completions = BoomClient._C()

        @property
        def chat(self):
            return BoomClient._Chat()

        def close(self):
            pass

    llm = OpenAICompatibleClient(client=BoomClient())
    with pytest.raises(LLMError, match="LLM 调用失败"):
        llm.chat([cm("user", "x")])


def test_openai_compatible_missing_lib_raises(monkeypatch):
    import src.llm_client.openai_compatible as oc

    monkeypatch.setattr(oc, "_OpenAI", None)
    with pytest.raises(LLMError):
        OpenAICompatibleClient(api_key="k")


# ---------------- build_llm_client 选型 ----------------
def test_build_llm_client_default_fake():
    llm = build_llm_client({})
    assert isinstance(llm, FakeLLMClient)


def test_build_llm_client_fake_with_options():
    llm = build_llm_client({"provider": "fake", "options": {"default_reply": "d"}})
    assert isinstance(llm, FakeLLMClient)
    assert llm.default_reply == "d"


def test_build_llm_client_openai_compatible():
    llm = build_llm_client(
        {"provider": "openai_compatible", "options": {"api_key": "test-key", "model": "m"}}
    )
    assert isinstance(llm, OpenAICompatibleClient)
    assert llm.model == "m"
    llm.close()


def test_llm_registry_typed():
    from src.llm_client.registry import llm_registry

    assert set(llm_registry.names) == {"fake", "openai_compatible"}
    assert issubclass(llm_registry.get("fake"), LLMClient)
