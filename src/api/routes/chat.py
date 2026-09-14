"""P5 API 层：聊天路由。"""
from fastapi import APIRouter, Depends

from src.api.dependencies import get_service
from src.api.schemas import ChatRequest, ChatResponse
from src.api.service import AgentService

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    service: AgentService = Depends(get_service),
) -> ChatResponse:
    """多轮连续对话：Agent 自动拆解任务、调度工具、返回回答与轨迹。"""
    return service.chat(req.query, req.session_id)
