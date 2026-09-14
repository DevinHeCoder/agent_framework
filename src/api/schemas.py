"""P5 API 层：请求/响应 Pydantic 模型。"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------- chat ----------------
class ChatRequest(BaseModel):
    """聊天请求。"""

    query: str = Field(..., min_length=1, max_length=2000, description="用户请求")
    session_id: Optional[str] = Field(
        None, description="会话 ID；缺省自动创建新会话"
    )


class TraceItem(BaseModel):
    """单步执行轨迹。"""

    step_id: int
    action: str
    args: Dict[str, Any] = Field(default_factory=dict)
    observation: str = ""
    status: str = "success"


class ChatResponse(BaseModel):
    """聊天响应。"""

    session_id: str
    answer: str
    success: bool
    steps_taken: int = 0
    trace: List[TraceItem] = Field(default_factory=list)


# ---------------- tools ----------------
class ToolSchemaOut(BaseModel):
    """工具 schema（供外部查看 / 后续接 function-calling）。"""

    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ToolsResponse(BaseModel):
    tools: List[ToolSchemaOut]


# ---------------- sessions ----------------
class SessionItem(BaseModel):
    session_id: str
    created_at: datetime
    last_active: datetime
    message_count: int = 0


# ---------------- system ----------------
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    enabled_tools: List[str]


class SystemInfoResponse(BaseModel):
    app: str
    version: str
    llm_provider: str
    memory_provider: str
    planner_provider: str
    agent_provider: str
    enabled_tools: List[str]
    active_sessions: int
