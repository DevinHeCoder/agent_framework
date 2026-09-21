"""P5 API 层：路由聚合。"""
from fastapi import APIRouter

from src.api.routes import chat, system, tools, usage

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(chat.router)
api_router.include_router(tools.router)
api_router.include_router(usage.router)
