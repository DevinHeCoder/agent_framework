"""短时记忆：进程内 dict + 滑动窗口。

- 读写快（纯内存），适合高频会话；
- 每会话保留最近 window_size 条消息（滑动窗口），防止无限膨胀；
- 进程退出后数据丢失，由长时记忆（Redis）兜底。
"""
from typing import Dict, List

from src.memory.base import BaseMemory, Message
from src.memory.registry import memory_registry


@memory_registry.register("in_memory")
class InMemoryMemory(BaseMemory):
    """进程内短时记忆，支持每会话滑动窗口。"""

    def __init__(self, window_size: int = 20) -> None:
        self.window_size = window_size
        self._store: Dict[str, List[Message]] = {}

    def add_message(self, session_id: str, msg: Message) -> None:
        msgs = self._store.setdefault(session_id, [])
        msgs.append(msg)
        self._trim(session_id)

    def get_messages(self, session_id: str) -> List[Message]:
        return list(self._store.get(session_id, []))

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    # ---------------- 附加能力（便于监控/测试） ----------------
    def list_sessions(self) -> List[str]:
        """返回全部活跃会话 id。"""
        return list(self._store.keys())

    def __len__(self) -> int:
        """返回所有会话的消息总数。"""
        return sum(len(v) for v in self._store.values())

    # ---------------- 内部 ----------------
    def _trim(self, session_id: str) -> None:
        msgs = self._store[session_id]
        if self.window_size and len(msgs) > self.window_size:
            del msgs[: len(msgs) - self.window_size]
