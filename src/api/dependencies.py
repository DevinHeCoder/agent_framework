"""P5 API 层：依赖注入。从 app.state 取全局 AgentService 单例。"""
from fastapi import Request

from src.api.service import AgentService


def get_service(request: Request) -> AgentService:
    """FastAPI 依赖：获取全局 Agent 服务实例。"""
    service: AgentService = request.app.state.service
    return service
