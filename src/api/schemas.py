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


class MessageItem(BaseModel):
    """单条会话消息（历史记录）。"""

    role: str
    content: str


class SessionMessagesResponse(BaseModel):
    """会话历史消息。"""

    session_id: str
    messages: List[MessageItem] = Field(default_factory=list)


# ---------------- system ----------------
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    enabled_tools: List[str]


class BrandingInfo(BaseModel):
    """白标信息：前端控制台品牌元素（由 branding 配置注入）。"""

    app_name: str = "轻量智能 Agent 工具编排框架"
    logo_text: str = "AGENT"
    logo_suffix: str = "·控制台"
    agent_label: str = "AGENT"
    primary_color: str = "#4F8CFF"
    accent_color: str = "#22D3EE"


class SystemInfoResponse(BaseModel):
    app: str
    version: str
    llm_provider: str
    memory_provider: str
    planner_provider: str
    agent_provider: str
    enabled_tools: List[str]
    active_sessions: int
    auth_required: bool = False
    branding: BrandingInfo = Field(default_factory=BrandingInfo)


# ---------------- usage ----------------
class UsageBucket(BaseModel):
    """单日用量（llm_calls / in_tokens / out_tokens / api_calls）。"""

    date: Optional[str] = None
    llm_calls: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    api_calls: int = 0


class UsageResponse(BaseModel):
    """用量监控：今日 / 累计 / 最近 7 天明细。"""

    today: UsageBucket = Field(default_factory=UsageBucket)
    total: UsageBucket = Field(default_factory=UsageBucket)
    days: List[UsageBucket] = Field(default_factory=list)
