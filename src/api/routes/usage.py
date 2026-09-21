"""P5.5 API 层：用量监控路由（需鉴权）。"""
from fastapi import APIRouter, Depends, Request

from src.api.auth import verify_api_key
from src.api.schemas import UsageBucket, UsageResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["usage"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/usage", response_model=UsageResponse)
async def usage(request: Request) -> UsageResponse:
    """用量快照：今日 / 累计 / 最近 7 天（LLM 调用次数 + token 消耗）。"""
    snap = request.app.state.usage.snapshot(days=7)
    return UsageResponse(
        today=UsageBucket(**snap["today"]),
        total=UsageBucket(**snap["total"]),
        days=[UsageBucket(**d) for d in snap["days"]],
    )
