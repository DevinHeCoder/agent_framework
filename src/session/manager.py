"""会话管理器：session_id 生命周期与每会话元数据（需求④：会话状态/多轮连续）。

职责边界:
- SessionManager 只负责会话「身份与元数据」（创建/活跃时间/消息数/删除）；
- 会话「内容持久化」由 memory 层负责（in_memory 进程内 / redis / hybrid 跨重启）；
- 二者组合即「会话状态持久化 + 多轮连续任务」的完整实现。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.memory.base import BaseMemory


@dataclass
class SessionInfo:
    """单个会话的元数据。"""

    session_id: str
    created_at: datetime
    last_active: datetime
    message_count: int = 0


class SessionManager:
    """会话生命周期管理。"""

    def __init__(
        self,
        memory: Optional[BaseMemory] = None,
        max_sessions: int = 1000,
    ) -> None:
        self._memory = memory
        self._max_sessions = max_sessions
        self._sessions: Dict[str, SessionInfo] = {}

    # ---------------- 生命周期 ----------------
    def create(self, session_id: Optional[str] = None) -> SessionInfo:
        """创建会话；指定 id 已存在时幂等返回（不覆盖历史）。"""
        if session_id:
            if session_id in self._sessions:
                return self._sessions[session_id]
            sid = session_id
        else:
            sid = self._new_id()
        now = datetime.now()
        info = SessionInfo(
            session_id=sid,
            created_at=now,
            last_active=now,
            message_count=self._count_messages(sid),
        )
        self._sessions[sid] = info
        return info

    def get(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: Optional[str] = None) -> SessionInfo:
        """取已有会话，不存在则创建（API 层的统一入口）。"""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create(session_id)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def touch(self, session_id: str) -> None:
        """更新活跃时间与消息数（会话使用后调用）。"""
        info = self._sessions.get(session_id)
        if info is None:
            return
        info.last_active = datetime.now()
        info.message_count = self._count_messages(session_id)

    def delete(self, session_id: str) -> bool:
        """删除会话元数据；若关联 memory，则同时清空该会话内容。"""
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        if self._memory is not None:
            self._memory.clear(session_id)
        return True

    # ---------------- 查询 ----------------
    def list(self) -> List[SessionInfo]:
        """按最近活跃倒序返回全部会话。"""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_active,
            reverse=True,
        )

    def __len__(self) -> int:
        return len(self._sessions)

    # ---------------- 内部 ----------------
    def _new_id(self) -> str:
        while True:
            sid = f"sess_{uuid.uuid4().hex[:10]}"
            if sid not in self._sessions:
                return sid

    def _count_messages(self, session_id: str) -> int:
        if self._memory is None:
            return 0
        return len(self._memory.get_messages(session_id))
