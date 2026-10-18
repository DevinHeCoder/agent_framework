"""P5 API 层：系统路由（健康检查 / 信息 / 会话管理）。"""
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.api.auth import verify_api_key
from src.api.dependencies import get_service
from src.api.schemas import (
    HealthResponse,
    SessionItem,
    SessionMessagesResponse,
    SystemInfoResponse,
)
from src.api.service import AgentService

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(service: AgentService = Depends(get_service)) -> HealthResponse:
    """健康检查（业务信息：版本 / 启用的工具）。"""
    return service.health()


@router.get("/healthz")
async def healthz() -> dict:
    """存活探针：进程活着即 200，不依赖任何外部组件（供负载均衡 / k8s liveness）。"""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(service: AgentService = Depends(get_service)):
    """就绪探针：依次检查 Redis / LLM client；任一失败返回 503 并列出失败项。"""
    result = service.readiness()
    status_code = 200 if result["status"] == "ready" else 503
    return JSONResponse(content=result, status_code=status_code)


@router.get("/api/v1/system", response_model=SystemInfoResponse)
async def root(service: AgentService = Depends(get_service)) -> SystemInfoResponse:
    """服务信息与各层选型（原根路径，已让位给前端控制台）。"""
    return service.system_info()


@router.get("/api/v1/sessions", response_model=List[SessionItem])
async def list_sessions(
    service: AgentService = Depends(get_service),
    _auth: None = Depends(verify_api_key),
) -> List[SessionItem]:
    """列出全部会话（按最近活跃倒序）。"""
    return service.list_sessions()


@router.delete("/api/v1/sessions/{session_id}")
async def delete_session(
    session_id: str,
    service: AgentService = Depends(get_service),
    _auth: None = Depends(verify_api_key),
) -> dict:
    """删除会话（含记忆内容）。"""
    return {"deleted": service.delete_session(session_id)}


@router.get(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
async def get_session_messages(
    session_id: str,
    service: AgentService = Depends(get_service),
    _auth: None = Depends(verify_api_key),
) -> SessionMessagesResponse:
    """读取会话历史消息（user/assistant 按时间顺序）。"""
    return service.get_session_messages(session_id)
