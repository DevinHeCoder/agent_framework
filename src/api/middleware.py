"""API 中间件：请求链路标识 + 安全加固（P0-1 / P0-4）。

RequestIDMiddleware:
- 读取请求头 X-Request-Id（客户端可传入，用于端到端追踪），缺失则生成 uuid4 短版；
- 写入 request.state.request_id 与 contextvar（src.utils.logger.request_id_var），
  使日志 filter 自动注入该 ID，一次请求的全链路日志可串；
- 响应头回写 X-Request-Id。

SecurityHeadersMiddleware:
- 统一安全响应头（nosniff / X-Frame-Options / CSP）；
- 请求体大小限制（Content-Length 超限返回 413，默认 1MB）。
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.utils.logger import request_id_var

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # 前端控制台含内联样式/脚本，故放行 inline（接口场景按需收紧）
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    ),
}


def _new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-Id") or _new_request_id()
        request.state.request_id = rid
        token = request_id_var.set(rid)
        response: Response | None = None
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
            # 正常路径回写请求 ID；异常路径（call_next 重抛）由 body 携带 request_id
            if response is not None:
                try:
                    response.headers["X-Request-Id"] = rid
                except Exception:  # pragma: no cover - 响应头不可变等极端情况
                    pass
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头 + 请求体大小限制（P0-4）。"""

    def __init__(self, app, *, max_body_bytes: int = 1_048_576) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        # 请求体大小限制：Content-Length 超限直接 413（GET/无 body 请求不受影响）
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            try:
                if int(content_length) > self.max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "PayloadTooLarge",
                            "message": f"请求体超过上限（{self.max_body_bytes} 字节）",
                            "request_id": getattr(request.state, "request_id", "-"),
                        },
                    )
            except ValueError:  # pragma: no cover - header 已 isdigit 校验
                pass

        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
