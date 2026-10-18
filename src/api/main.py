"""P5 API 层：FastAPI 应用入口（应用工厂，支持注入便于测试）。

启动:
    python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

或:
    uvicorn src.api.main:app --reload

前端控制台: 启动后访问 http://localhost:8000/（static/index.html）
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.auth import AuthConfig, RateLimiter
from src.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from src.api.routes import api_router
from src.api.service import AgentService
from src.api.usage import UsageTracker
from src.common.constants import PROJECT_ROOT
from src.common.exceptions import AgentFrameworkError
from src.common.security import validate_runtime_security
from src.utils.config_loader import load_config
from src.utils.logger import get_logger, request_id_var

logger = get_logger("agent_framework.api.main")


def _to_bool(value: object) -> bool:
    """布尔规范化：兼容 YAML 占位符默认值返回的字符串（'false'/'0'/''）。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def create_app(
    config: Optional[dict] = None,
    service: Optional[AgentService] = None,
) -> FastAPI:
    """创建 FastAPI 应用；可注入 config / service 便于测试与演示。"""
    cfg = config or load_config()
    # P0-3 生产安全校验：production 下空/占位 LLM 密钥直接拒绝启动（防裸奔）
    validate_runtime_security(cfg)
    app_cfg = cfg.get("app", {})
    app_env = str(app_cfg.get("env", "development")).lower()

    # P0-1 可插拔 Sentry：仅当配置了 DSN 才初始化（客户私有化环境不依赖云服务）
    _init_sentry_if_configured(cfg, app_env)

    app = FastAPI(
        title=app_cfg.get("name", "Agent Framework"),
        version=app_cfg.get("version", "0.1.0"),
        description="轻量智能 Agent 工具编排框架：统一工具注册、LLM 任务拆解、"
        "双缓存记忆、会话持久化、异常重试与兜底",
    )

    # 中间件按"后注册先执行"（LIFO）排列：RequestID 最外层 → 安全头/CORS → 路由
    # P0-4 安全加固：请求体上限 + 安全响应头
    sec_cfg = (cfg.get("server", {}) or {}).get("security", {}) or {}
    max_body_mb = int(sec_cfg.get("max_body_mb", 1) or 1)
    app.add_middleware(
        SecurityHeadersMiddleware,
        max_body_bytes=max(1, max_body_mb) * 1024 * 1024,
    )

    # P0-4 CORS 白名单：仅配置了来源才开启；空=仅同源（禁止 *）
    cors_origins = [
        o.strip()
        for o in str(sec_cfg.get("cors_origins") or "").split(",")
        if o and o.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # P0-1 请求链路标识：X-Request-Id 生成/透传 + 日志 context 注入（最外层）
    app.add_middleware(RequestIDMiddleware)

    # P0-1 全局异常兜底：统一错误 JSON（code/message/request_id）+ 完整 traceback
    _register_exception_handler(app)

    # 用量监控（Redis 计数，降级内存）：注入 service 的 LLM 客户端用于 token 统计
    memory_cfg = cfg.get("memory", {})
    redis_url = (
        memory_cfg.get("long_term", {}) or {}
    ).get("redis_url") or memory_cfg.get("options", {}).get("redis_url")
    app.state.usage = UsageTracker(redis_url=redis_url)

    # 全局单例服务（含全部层组装）；无论 service 来源，统一注入用量上报器
    svc = service or AgentService.build_from_config(cfg, usage=app.state.usage)
    if svc.llm is not None:
        svc.llm.set_usage_sink(app.state.usage)
    app.state.service = svc

    # API 鉴权状态（依赖注入读取；health/system 公开，其余端点校验 Key）
    auth_cfg = cfg.get("server", {}).get("auth", {})
    app.state.auth_config = AuthConfig(
        enabled=_to_bool(auth_cfg.get("enabled", False)),
        token=auth_cfg.get("token") or "",
        rate_limit_per_minute=int(auth_cfg.get("rate_limit_per_minute", 60)),
    )
    app.state.rate_limiter = RateLimiter(app.state.auth_config.rate_limit_per_minute)

    # API 路由（先注册，优先匹配）
    app.include_router(api_router)

    # 前端控制台静态托管：/ 与 /static/* -> static/index.html
    static_dir = PROJECT_ROOT / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="console")
    return app


# ---------------- 可观测性辅助（P0-1） ----------------
def _init_sentry_if_configured(cfg: dict, app_env: str) -> None:
    """Sentry 可插拔初始化：MONITORING_SENTRY_DSN 为空则完全跳过。"""
    monitoring = (cfg.get("server", {}) or {}).get("monitoring", {}) or {}
    dsn = str(monitoring.get("sentry_dsn") or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk  # 可选依赖：未安装时降级为告警，不阻断启动

        sentry_sdk.init(dsn=dsn, environment=app_env)
        logger.info("Sentry 已启用（environment=%s）", app_env)
    except Exception as e:  # pragma: no cover - 取决于可选依赖环境
        logger.warning("Sentry 初始化失败（不影响服务启动）: %s", e)


def _register_exception_handler(app: FastAPI) -> None:
    """全局异常兜底：任何未捕获异常 → 统一 JSON（code/message/request_id）。

    AgentFrameworkError 体系映射为 500（框架内部错误，含完整上下文）；
    FastAPI 自带的 HTTPException / RequestValidationError 处理不受影响。
    """

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id_var.get()
        if rid == "-":
            rid = getattr(request.state, "request_id", "-")

        if isinstance(exc, AgentFrameworkError):
            code = type(exc).__name__
            message = str(exc)
            logger.error(
                "unhandled framework error request_id=%s code=%s: %s",
                rid, code, message,
                exc_info=exc,
            )
        else:
            code = "InternalError"
            message = "服务器内部错误"
            logger.error(
                "unhandled exception request_id=%s: %s",
                rid, type(exc).__name__,
                exc_info=exc,
            )
        return JSONResponse(
            status_code=500,
            content={"code": code, "message": message, "request_id": rid},
        )


# 默认应用实例（uvicorn 入口）
app = create_app()
