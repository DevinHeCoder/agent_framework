"""Fake LLM 客户端：无需 API Key，驱动全链路开发与测试。

能力:
- responses 队列：按顺序返回预设回复（先进先出），可模拟多轮任务规划；
- responder 回调：按消息内容动态生成回复（优先级高于队列）；
- 记录每次调用的 messages / kwargs，便于断言调用形态。
"""
from typing import Callable, List, Optional

from src.llm_client.base import ChatMessage, LLMClient
from src.llm_client.registry import llm_registry

Responder = Callable[[List[ChatMessage], dict], str]


@llm_registry.register("fake")
class FakeLLMClient(LLMClient):
    """可编程假客户端（无网络、无 Key、确定性输出）。"""

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        default_reply: str = "【fake】已收到你的消息。",
        responder: Optional[Responder] = None,
    ) -> None:
        super().__init__()
        self._responses = list(responses or [])
        self.default_reply = default_reply
        self.responder = responder
        self.calls: List[tuple] = []  # 每次调用的 (messages, kwargs)

    def chat(self, messages: List[ChatMessage], **kwargs) -> str:
        self.calls.append((list(messages), dict(kwargs)))
        if self.responder is not None:
            content = self.responder(messages, kwargs)
        elif self._responses:
            content = self._responses.pop(0)
        else:
            content = self.default_reply
        # 用量统计：fake 按字符数粗估 token（演示/测试也可看到趋势）
        self._report_usage(self.model if hasattr(self, "model") else "fake",
                           sum(len(m.content) for m in messages) // 2,
                           len(content) // 2)
        return content

    def close(self) -> None:
        self.calls.clear()
