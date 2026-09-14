"""长时记忆：Redis 持久化 + TTL。

- 消息 JSON 序列化后存入 Redis List（每会话一个 key，天然保序）；
- 每次写入刷新 TTL（默认 1 天），过期自动清理；
- 支持注入 client（便于测试 / 复用连接池）；redis 库未安装时明确报错。

注意：本模块对 redis 库做惰性导入——不安装 redis 也能 import 本包，
仅在使用 provider=redis / hybrid 且未注入 client 时才需要 redis 库。
"""
import json
from typing import List, Optional

from src.common.exceptions import MemoryError
from src.memory.base import BaseMemory, Message
from src.memory.registry import memory_registry

try:  # 惰性依赖：未安装 redis 时 redis_lib = None
    import redis as redis_lib
except ImportError:  # pragma: no cover - 取决于运行环境
    redis_lib = None

_DEFAULT_URL = "redis://localhost:6379/0"
_DEFAULT_TTL = 86400
_DEFAULT_PREFIX = "agent:session:"


@memory_registry.register("redis")
class RedisMemory(BaseMemory):
    """基于 Redis List 的持久化会话记忆。"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl_seconds: int = _DEFAULT_TTL,
        key_prefix: str = _DEFAULT_PREFIX,
        client=None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        if client is not None:
            self._client = client
        else:
            if redis_lib is None:
                raise MemoryError(
                    "未安装 redis 库（pip install redis），无法使用 Redis 记忆；"
                    "或改用 provider=in_memory / hybrid"
                )
            try:
                self._client = redis_lib.Redis.from_url(
                    redis_url or _DEFAULT_URL, decode_responses=True
                )
            except Exception as e:
                raise MemoryError(f"初始化 Redis 客户端失败: {e}") from e

    def add_message(self, session_id: str, msg: Message) -> None:
        key = self._key(session_id)
        data = json.dumps({"role": msg.role, "content": msg.content}, ensure_ascii=False)
        try:
            pipe = self._client.pipeline()
            pipe.rpush(key, data)
            pipe.expire(key, self.ttl_seconds)
            pipe.execute()
        except Exception as e:
            raise MemoryError(f"Redis 写入失败: {e}") from e

    def get_messages(self, session_id: str) -> List[Message]:
        try:
            raw_list = self._client.lrange(self._key(session_id), 0, -1)
        except Exception as e:
            raise MemoryError(f"Redis 读取失败: {e}") from e

        msgs: List[Message] = []
        for raw in raw_list or []:
            try:
                obj = json.loads(raw)
                msgs.append(Message(role=obj["role"], content=obj["content"]))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # 单条损坏跳过，不导致整会话失败
        return msgs

    def clear(self, session_id: str) -> None:
        try:
            self._client.delete(self._key(session_id))
        except Exception as e:
            raise MemoryError(f"Redis 删除失败: {e}") from e

    # ---------------- 内部 ----------------
    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"
