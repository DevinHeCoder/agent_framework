"""双缓存组合记忆：短时（进程内）快速读写 + 长时（Redis）跨重启兜底。

冷热分层策略：
- add_message：写入短时缓存；persist_on_write=True 时同步写入长时（保证不丢）；
- get_messages：短时未命中（如进程重启导致缓存清空）→ 从长时恢复并回填短时；
- clear：两层同时清空。

这样兼顾「快」（进程内 O(1) 读写）与「稳」（Redis 持久化、重启可恢复），
正是需求点「短时 + 长时双缓存记忆机制」的落地形态。
"""
from src.memory.base import BaseMemory, Message
from src.memory.registry import memory_registry


@memory_registry.register("hybrid")
class HybridMemory(BaseMemory):
    """冷热分层双缓存记忆。"""

    def __init__(
        self,
        short_term: BaseMemory,
        long_term: BaseMemory,
        persist_on_write: bool = False,
    ) -> None:
        self.short_term = short_term
        self.long_term = long_term
        self.persist_on_write = persist_on_write

    def add_message(self, session_id: str, msg: Message) -> None:
        self.short_term.add_message(session_id, msg)
        if self.persist_on_write:
            self.long_term.add_message(session_id, msg)

    def get_messages(self, session_id: str) -> list[Message]:
        msgs = self.short_term.get_messages(session_id)
        if not msgs:
            # 短时未命中（如进程重启）→ 从长时恢复，并回填短时缓存
            msgs = self.long_term.get_messages(session_id)
            for m in msgs:
                self.short_term.add_message(session_id, m)
        return msgs

    def clear(self, session_id: str) -> None:
        self.short_term.clear(session_id)
        self.long_term.clear(session_id)
