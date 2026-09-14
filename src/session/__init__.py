"""session 包：会话管理（需求④：会话状态持久化，支撑多轮连续任务）。"""
from src.session.manager import SessionInfo, SessionManager

__all__ = ["SessionManager", "SessionInfo"]
