"""
LLM 客户端抽象基类：ChatMessage + LLMClient。

上层（Planner / Agent）只依赖 LLMClient 的 chat()，可通过 Registry 无缝
切换实现：真实场景用 openai_compatible（OpenAI 兼容协议），开发/测试用
fake（无 key 驱动全链路）。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class ChatMessage:
    """对话消息（与大模型 API 对齐的通用形态）。

    属性:
        role: system / user / assistant / tool
        content: 消息文本
    """

    role: str
    content: str


class LLMClient(ABC):
    """大模型客户端统一接口。"""

    @abstractmethod
    def chat(self, messages: List[ChatMessage], **kwargs) -> str:
        """多轮对话，返回 assistant 文本。

        参数:
            messages: 对话历史（含 system 指令）
            kwargs: 透传参数（temperature / max_tokens 等）
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """释放底层连接资源。"""
        pass
