"""P5 API 层：系统路由（健康检查 / 信息 / 会话管理）。"""
from typing import List

from fastapi import APIRouter, Depends

from src.api.dependencies import get_service
from src.api.schemas import HealthResponse, SessionItem, SystemInfoResponse
from src.api.service import AgentService

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(service: AgentService = Depends(get_service)) -> HealthResponse:
    """健康检查。"""
    return service.health()


@router.get("/", response_model=SystemInfoResponse)
async def root(service: AgentService = Depends(get_service)) -> SystemInfoResponse:
    """服务信息与各层选型。"""
    return service.system_info()


@router.get("/api/v1/sessions", response_model=List[SessionItem])
async def list_sessions(
    service: AgentService = Depends(get_service),
) -> List[SessionItem]:
    """列出全部会话（按最近活跃倒序）。"""
    return service.list_sessions()


@router.delete("/api/v1/sessions/{session_id}")
async def delete_session(
    session_id: str,
    service: AgentService = Depends(get_service),
) -> dict:
    """删除会话（含记忆内容）。"""
    return {"deleted": service.delete_session(session_id)}
