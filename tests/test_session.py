"""P5 会话管理单测：创建/幂等/查询/活跃刷新/删除联动记忆/排序。"""
import pytest

from src.memory.in_memory_memory import InMemoryMemory
from src.memory.base import Message
from src.session import SessionManager


def test_create_auto_id():
    m = SessionManager()
    info = m.create()
    assert info.session_id.startswith("sess_")
    assert m.exists(info.session_id)
    assert len(m) == 1


def test_create_custom_id_idempotent():
    m = SessionManager()
    a = m.create("my-session")
    b = m.create("my-session")  # 幂等：不覆盖
    assert a is b
    assert len(m) == 1


def test_get_or_create():
    m = SessionManager()
    a = m.get_or_create("s1")
    assert a.session_id == "s1"
    b = m.get_or_create("s1")
    assert b is a


def test_get_missing_returns_none():
    m = SessionManager()
    assert m.get("nope") is None
    assert m.exists("nope") is False


def test_touch_updates_message_count():
    mem = InMemoryMemory()
    m = SessionManager(memory=mem)
    info = m.create("s1")
    assert info.message_count == 0
    mem.add_message("s1", Message(role="user", content="hi"))
    m.touch("s1")
    assert info.message_count == 1


def test_delete_clears_memory():
    mem = InMemoryMemory()
    m = SessionManager(memory=mem)
    m.create("s1")
    mem.add_message("s1", Message(role="user", content="hi"))
    assert m.delete("s1") is True
    assert mem.get_messages("s1") == []
    assert m.delete("s1") is False  # 已不存在


def test_list_sorted_by_last_active():
    m = SessionManager()
    m.create("a")
    m.create("b")
    m.touch("a")
    names = [s.session_id for s in m.list()]
    assert names[0] == "a"  # 最近活跃在前


def test_session_ids_unique():
    m = SessionManager()
    ids = {m.create().session_id for _ in range(20)}
    assert len(ids) == 20
