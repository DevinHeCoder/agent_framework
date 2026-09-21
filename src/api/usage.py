"""P5.5 用量监控：LLM 调用次数与 token 消耗统计。

设计：
- 按天聚合：llm_calls / in_tokens / out_tokens / api_calls；
- 优先用 Redis 持久计数（与长时记忆共用 agent-redis），Redis 不可用时降级进程内内存计数；
- snapshot() 返回今日、累计、最近 N 天明细，供 /api/v1/usage 与前端控制台展示。

键设计: agent:usage:{yyyy-mm-dd}:{metric}
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional

try:  # 惰性依赖：未安装 redis 时降级内存计数
    import redis as redis_lib
except ImportError:  # pragma: no cover - 取决于运行环境
    redis_lib = None

_PREFIX = "agent:usage:"
_METRICS = ("llm_calls", "in_tokens", "out_tokens", "api_calls")


class UsageTracker:
    """用量统计器（Redis 优先，内存降级）。"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        client=None,
    ) -> None:
        self._mem: Dict[str, int] = {}
        self._client = None
        if client is not None:
            self._client = client
        elif redis_url and redis_lib is not None:
            try:
                self._client = redis_lib.Redis.from_url(
                    redis_url, decode_responses=True
                )
            except Exception:  # pragma: no cover - 网络环境差异
                self._client = None

    # ---------------- 底层计数 ----------------
    def _incr(self, key: str, delta: int = 1) -> None:
        if delta <= 0:
            return
        if self._client is not None:
            try:
                self._client.incrby(key, delta)
                return
            except Exception:
                self._client = None  # 一次性降级：Redis 异常后转内存
        self._mem[key] = self._mem.get(key, 0) + delta

    def _get(self, key: str) -> int:
        if self._client is not None:
            try:
                v = self._client.get(key)
                return int(v) if v else 0
            except Exception:
                self._client = None
        return self._mem.get(key, 0)

    # ---------------- 语义上报 ----------------
    def report_llm(self, model: str, input_tokens: int, output_tokens: int) -> None:
        """每次 LLM 调用成功后上报 token 消耗。"""
        d = date.today().isoformat()
        self._incr(f"{_PREFIX}{d}:llm_calls")
        self._incr(f"{_PREFIX}{d}:in_tokens", int(input_tokens))
        self._incr(f"{_PREFIX}{d}:out_tokens", int(output_tokens))

    def report_api_call(self) -> None:
        """每次鉴权放行的 API 请求计数（观察整体调用压力）。"""
        d = date.today().isoformat()
        self._incr(f"{_PREFIX}{d}:api_calls")

    # ---------------- 快照 ----------------
    def snapshot(self, days: int = 7) -> dict:
        """聚合快照：today / total / days（最近 days 天，升序）。"""
        today = date.today()

        def bucket(d: date) -> dict:
            p = f"{_PREFIX}{d.isoformat()}"
            return {m: self._get(f"{p}:{m}") for m in _METRICS}

        total = {m: 0 for m in _METRICS}
        day_list = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            b = bucket(d)
            day_list.append({"date": d.isoformat(), **b})
            for m in _METRICS:
                total[m] += b[m]
        return {"today": bucket(today), "total": total, "days": day_list}
