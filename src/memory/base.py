"""
记忆层抽象基类：Message + BaseMemory。

Message 是记忆的最小单元（role + content）；BaseMemory 定义会话记忆的
统一读写接口，短时（InMemory）与长时（Redis）及双缓存组合均实现该接口，
上层（Agent / Session）只依赖 BaseMemory，可无缝替换记忆后端。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Message:
    """单条会话消息。

    属性:
        role: 消息角色，user / assistant / tool / system
        content: 消息文本
    """

    role: str
    content: str


class BaseMemory(ABC):
    """会话记忆统一接口（按 session_id 隔离多会话）。"""

    @abstractmethod
    def add_message(self, session_id: str, msg: Message) -> None:
        """向指定会话追加一条消息。"""
        pass

    @abstractmethod
    def get_messages(self, session_id: str) -> List[Message]:
        """读取指定会话的全部消息（按时间顺序），会话不存在返回空列表。"""
        pass

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """清空指定会话记忆。"""
        pass
