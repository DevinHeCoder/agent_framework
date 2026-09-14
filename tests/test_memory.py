"""P2 记忆层单测：短时滑动窗口、Redis 长时持久化（FakeClient）、双缓存冷热恢复、build_memory 选型。"""
import pytest

from src.common.exceptions import MemoryError, RegistryError
from src.memory import build_memory
from src.memory.base import BaseMemory, Message
from src.memory.hybrid_memory import HybridMemory
from src.memory.in_memory_memory import InMemoryMemory
from src.memory.redis_memory import RedisMemory


# ---------------- FakeRedis 客户端（模拟 redis-py 子集） ----------------
class FakeRedis:
    """内存版 Redis 客户端：支持 rpush / lrange / expire / delete / pipeline。"""

    def __init__(self):
        self._lists = {}
        self._ttl = {}

    def rpush(self, key, *values):
        self._lists.setdefault(key, []).extend(values)
        return len(self._lists[key])

    def lrange(self, key, start, end):
        vals = self._lists.get(key, [])
        n = len(vals)
        if end == -1 or end >= n:
            end = n - 1
        if start >= n:
            return []
        return vals[start:end + 1]

    def expire(self, key, ttl):
        self._ttl[key] = ttl
        return True

    def delete(self, key):
        self._lists.pop(key, None)
        self._ttl.pop(key, None)
        return True

    def pipeline(self):
        return _Pipe(self)


class _Pipe:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._cmds = []

    def rpush(self, key, *values):
        self._cmds.append(("rpush", key, values))
        return self

    def expire(self, key, ttl):
        self._cmds.append(("expire", key, ttl))
        return self

    def execute(self):
        for kind, key, arg in self._cmds:
            if kind == "rpush":
                self._redis.rpush(key, *arg)
            else:
                self._redis.expire(key, arg)
        self._cmds = []


def msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


# ---------------- InMemoryMemory ----------------
def test_in_memory_add_get_clear():
    mem = InMemoryMemory()
    mem.add_message("s1", msg("user", "你好"))
    mem.add_message("s1", msg("assistant", "你好！"))
    assert [m.content for m in mem.get_messages("s1")] == ["你好", "你好！"]
    mem.clear("s1")
    assert mem.get_messages("s1") == []
    assert mem.get_messages("不存在") == []


def test_in_memory_sliding_window():
    mem = InMemoryMemory(window_size=3)
    for i in range(5):
        mem.add_message("s1", msg("user", f"m{i}"))
    got = [m.content for m in mem.get_messages("s1")]
    assert got == ["m2", "m3", "m4"]  # 只保留最近 3 条


def test_in_memory_session_isolation():
    mem = InMemoryMemory()
    mem.add_message("a", msg("user", "A"))
    mem.add_message("b", msg("user", "B"))
    assert [m.content for m in mem.get_messages("a")] == ["A"]
    assert [m.content for m in mem.get_messages("b")] == ["B"]


def test_in_memory_no_window():
    mem = InMemoryMemory(window_size=0)  # 0 = 不裁剪
    for i in range(50):
        mem.add_message("s1", msg("user", str(i)))
    assert len(mem.get_messages("s1")) == 50


# ---------------- RedisMemory（注入 FakeClient） ----------------
def test_redis_add_get_preserves_order():
    r = FakeRedis()
    mem = RedisMemory(client=r)
    mem.add_message("s1", msg("user", "q1"))
    mem.add_message("s1", msg("tool", "r1"))
    mem.add_message("s1", msg("assistant", "a1"))
    got = mem.get_messages("s1")
    assert [(m.role, m.content) for m in got] == [
        ("user", "q1"), ("tool", "r1"), ("assistant", "a1"),
    ]


def test_redis_ttl_set():
    r = FakeRedis()
    mem = RedisMemory(client=r, ttl_seconds=3600)
    mem.add_message("s1", msg("user", "x"))
    assert r._ttl["agent:session:s1"] == 3600


def test_redis_clear_and_missing():
    r = FakeRedis()
    mem = RedisMemory(client=r)
    mem.add_message("s1", msg("user", "x"))
    mem.clear("s1")
    assert mem.get_messages("s1") == []
    assert mem.get_messages("不存在") == []


def test_redis_corrupt_entry_skipped():
    r = FakeRedis()
    r.rpush("agent:session:s1", "not-json", '{"role": "user", "content": "ok"}')
    mem = RedisMemory(client=r)
    got = mem.get_messages("s1")
    assert len(got) == 1 and got[0].content == "ok"


def test_redis_missing_lib_raises(monkeypatch):
    import src.memory.redis_memory as rm

    monkeypatch.setattr(rm, "redis_lib", None)
    with pytest.raises(MemoryError):
        RedisMemory(redis_url="redis://localhost:6379/0")


# ---------------- HybridMemory（双缓存冷热分层） ----------------
def test_hybrid_reads_short_term_first():
    short = InMemoryMemory()
    long_ = RedisMemory(client=FakeRedis())
    mem = HybridMemory(short_term=short, long_term=long_)
    mem.add_message("s1", msg("user", "short-only"))  # 默认不双写
    assert mem.get_messages("s1")[0].content == "short-only"
    assert long_.get_messages("s1") == []  # 长时未写入


def test_hybrid_restore_from_long_term_after_restart():
    """模拟进程重启：短时缓存清空，从长时恢复并回填短时。"""
    long_ = RedisMemory(client=FakeRedis())
    long_.add_message("s1", msg("user", "旧消息"))

    mem = HybridMemory(short_term=InMemoryMemory(), long_term=long_, persist_on_write=False)
    got = mem.get_messages("s1")
    assert [m.content for m in got] == ["旧消息"]
    # 恢复后回填短时缓存
    assert mem.short_term.get_messages("s1")[0].content == "旧消息"


def test_hybrid_persist_on_write_double_writes():
    short = InMemoryMemory()
    long_ = RedisMemory(client=FakeRedis())
    mem = HybridMemory(short_term=short, long_term=long_, persist_on_write=True)
    mem.add_message("s1", msg("user", "双写"))
    assert mem.short_term.get_messages("s1")[0].content == "双写"
    assert mem.long_term.get_messages("s1")[0].content == "双写"


def test_hybrid_clear_both_layers():
    short = InMemoryMemory()
    long_ = RedisMemory(client=FakeRedis())
    mem = HybridMemory(short_term=short, long_term=long_, persist_on_write=True)
    mem.add_message("s1", msg("user", "x"))
    mem.clear("s1")
    assert short.get_messages("s1") == []
    assert long_.get_messages("s1") == []


# ---------------- build_memory 选型 ----------------
def test_build_memory_default_in_memory():
    mem = build_memory({})
    assert isinstance(mem, InMemoryMemory)


def test_build_memory_in_memory_with_window():
    mem = build_memory({"provider": "in_memory", "window_size": 5})
    assert isinstance(mem, InMemoryMemory)
    assert mem.window_size == 5


def test_build_memory_unknown_provider_falls_back():
    # 未知 provider 目前兜底为 in_memory（可扩展为抛错）
    mem = build_memory({"provider": "no_such"})
    assert isinstance(mem, InMemoryMemory)


def test_memory_registry_typed():
    from src.memory.registry import memory_registry

    assert set(memory_registry.names) == {"in_memory", "redis", "hybrid"}
    assert issubclass(memory_registry.get("redis"), BaseMemory)


# ---------------- 真实 Redis 集成（本机有 Redis 服务则运行，否则跳过） ----------------
def _redis_available() -> bool:
    try:
        import redis as redis_lib

        r = redis_lib.Redis.from_url(
            "redis://localhost:6379/0", socket_connect_timeout=2
        )
        return bool(r.ping())
    except Exception:
        return False


def test_redis_real_integration():
    if not _redis_available():
        pytest.skip(
            "本机无 Redis 服务；可运行: docker run -d --name agent-framework-redis "
            "-p 6379:6379 redis:7-alpine"
        )
    mem = RedisMemory(redis_url="redis://localhost:6379/0", ttl_seconds=300)
    mem.add_message("it", msg("user", "q1"))
    mem.add_message("it", msg("assistant", "a1"))
    assert [m.content for m in mem.get_messages("it")] == ["q1", "a1"]
    mem.clear("it")
    assert mem.get_messages("it") == []
