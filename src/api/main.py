"""P5 API 层：FastAPI 应用入口（应用工厂，支持注入便于测试）。

启动:
    python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

或:
    uvicorn src.api.main:app --reload

前端控制台: 启动后访问 http://localhost:8000/（static/index.html）
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.auth import AuthConfig, RateLimiter
from src.api.routes import api_router
from src.api.service import AgentService
from src.api.usage import UsageTracker
from src.common.constants import PROJECT_ROOT
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

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
    app_cfg = cfg.get("app", {})

    app = FastAPI(
        title=app_cfg.get("name", "Agent Framework"),
        version=app_cfg.get("version", "0.1.0"),
        description="轻量智能 Agent 工具编排框架：统一工具注册、LLM 任务拆解、"
        "双缓存记忆、会话持久化、异常重试与兜底",
    )

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


# 默认应用实例（uvicorn 入口）
app = create_app()
