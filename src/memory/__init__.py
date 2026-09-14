"""
memory 包：统一记忆入口（短时 / 长时 / 双缓存组合，按配置选型）。

用法::

    from src.memory import build_memory
    mem = build_memory(cfg.get("memory"))   # cfg 来自 load_config()
    mem.add_message("s1", Message(role="user", content="你好"))
    mem.get_messages("s1")

配置选型（config/settings.yaml 的 memory 段）:
    provider: in_memory | redis | hybrid
"""
from __future__ import annotations

from typing import Optional

from src.memory.base import BaseMemory, Message
from src.memory.hybrid_memory import HybridMemory
from src.memory.in_memory_memory import InMemoryMemory
from src.memory.redis_memory import RedisMemory
from src.memory.registry import memory_registry

__all__ = [
    "BaseMemory",
    "Message",
    "memory_registry",
    "build_memory",
    "InMemoryMemory",
    "RedisMemory",
    "HybridMemory",
]


def build_memory(config: Optional[dict] = None) -> BaseMemory:
    """按配置构建记忆实例（短时 / 长时 / 双缓存组合）。

    参数:
        config: memory 配置段；缺省按 in_memory 构建。
    """
    cfg = config or {}
    provider = cfg.get("provider", "in_memory")

    if provider == "hybrid":
        short_cfg = cfg.get("short_term", {})
        long_cfg = cfg.get("long_term", {})
        short = memory_registry.create(
            "in_memory", window_size=short_cfg.get("window_size", 20)
        )
        long = memory_registry.create(
            "redis",
            redis_url=long_cfg.get("redis_url"),
            ttl_seconds=long_cfg.get("ttl_seconds", 86400),
        )
        return memory_registry.create(
            "hybrid", short_term=short, long_term=long, persist_on_write=True
        )

    if provider == "redis":
        return memory_registry.create(
            "redis",
            redis_url=cfg.get("redis_url"),
            ttl_seconds=cfg.get("ttl_seconds", 86400),
        )

    # 默认 in_memory（含未知 provider 以外的兜底）
    return memory_registry.create(
        "in_memory", window_size=cfg.get("window_size", 20)
    )
