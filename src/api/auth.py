"""P5 API 鉴权：API Key 校验 + 进程内频率限制。

设计：
- 配置开关 server.auth.enabled=false 时全部放行（本地开发/演示）；
- enabled=true 时，除 /health、/api/v1/system 外的 API 要求
  ``X-API-Key: <token>``（也兼容 ``Authorization: Bearer <token>``）；
- RateLimiter 按 Key（或 IP）做滑动窗口限流，防止 Key 泄露后被刷 LLM 额度。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request


@dataclass
class AuthConfig:
    """鉴权配置快照（create_app 时从 config 提取）。"""

    enabled: bool = False
    token: str = ""
    rate_limit_per_minute: int = 60


class RateLimiter:
    """滑动窗口限流：同一 Key 在 60s 窗口内最多 N 次请求。"""

    def __init__(self, per_minute: int = 0) -> None:
        self.per_minute = per_minute
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.time()
        dq = self._hits.setdefault(key, deque())
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= self.per_minute:
            return False
        dq.append(now)
        return True


def _extract_key(request: Request, token: str) -> Optional[str]:
    """从请求头取 API Key；返回 None 表示未提供。"""
    key = request.headers.get("x-api-key")
    if key:
        return key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def verify_api_key(request: Request) -> None:
    """FastAPI 依赖：校验 API Key 并执行限流。

    命中以下情形抛 401 / 429，否则放行：
    - 鉴权关闭：直接放行（本地开发）；
    - 鉴权开启且 token 未配置：拒绝一切请求（防御性默认）；
    - 未提供 / 错误的 Key：401；
    - 限流超限：429。
    """
    cfg: AuthConfig = request.app.state.auth_config
    if not cfg.enabled:
        return
    if not cfg.token:
        raise HTTPException(status_code=401, detail="服务未配置访问令牌，请联系管理员")

    key = _extract_key(request, cfg.token)
    if not key or key != cfg.token:
        raise HTTPException(status_code=401, detail="缺少或无效的 API Key")

    limiter: RateLimiter = request.app.state.rate_limiter
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试（限流窗口 60 秒）",
        )

    # 用量监控：每次鉴权放行的请求计数（观察整体调用压力）
    usage = getattr(request.app.state, "usage", None)
    if usage is not None:
        try:
            usage.report_api_call()
        except Exception:
            pass
