"""P5 API 层：工具路由（工具注册中心对外视图）。"""
from fastapi import APIRouter, Depends

from src.api.auth import verify_api_key
from src.api.dependencies import get_service
from src.api.schemas import ToolsResponse
from src.api.service import AgentService

router = APIRouter(prefix="/api/v1", tags=["tools"], dependencies=[Depends(verify_api_key)])


@router.get("/tools", response_model=ToolsResponse)
async def list_tools(
    service: AgentService = Depends(get_service),
) -> ToolsResponse:
    """返回当前注册的全部工具 schema。"""
    return service.list_tools()
