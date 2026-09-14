"""P5 API 层：FastAPI 应用入口（应用工厂，支持注入便于测试）。

启动:
    python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

或:
    uvicorn src.api.main:app --reload
"""
from typing import Optional

from fastapi import FastAPI

from src.api.routes import api_router
from src.api.service import AgentService
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

logger = get_logger("agent_framework.api.main")


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

    # 全局单例服务（含全部层组装）
    app.state.service = service or AgentService.build_from_config(cfg)

    # 路由
    app.include_router(api_router)
    return app


# 默认应用实例（uvicorn 入口）
app = create_app()
