"""P5 API 层：业务服务（组装各层 + 暴露给路由的纯逻辑）。"""
from __future__ import annotations

from typing import List, Optional

from src.agent import build_agent
from src.api.schemas import (
    ChatResponse,
    HealthResponse,
    SessionItem,
    SystemInfoResponse,
    ToolSchemaOut,
    ToolsResponse,
    TraceItem,
)
from src.llm_client import build_llm_client
from src.llm_client.base import LLMClient
from src.memory import build_memory
from src.planner import build_planner
from src.session import SessionManager
from src.tool import build_tool_registry, list_tool_schemas
from src.utils.config_loader import load_config


class AgentService:
    """Agent 编排服务的业务门面：供 FastAPI 路由调用。"""

    def __init__(self, config, agent, memory, tool_registry, sessions):
        self.config = config
        self.agent = agent
        self.memory = memory
        self.tool_registry = tool_registry
        self.sessions = sessions

    # ---------------- 组装 ----------------
    @classmethod
    def build_from_config(cls, config=None, *, llm: Optional[LLMClient] = None) -> "AgentService":
        """按配置一次性组装全部层（可注入 llm 便于测试/演示）。"""
        cfg = config or load_config()
        tool_cfg = cfg.get("tool", {})
        enabled_tools = tool_cfg.get("enabled")

        tool_registry = build_tool_registry(enabled=enabled_tools)
        memory = build_memory(cfg.get("memory"))
        llm = llm or build_llm_client(cfg.get("llm"))
        planner = build_planner(cfg.get("planner"), llm=llm)
        agent = build_agent(
            cfg.get("agent"),
            llm=llm,
            memory=memory,
            planner=planner,
            tool_registry=tool_registry,
            tool_config=tool_cfg,
            enabled_tools=enabled_tools,
        )
        sessions = SessionManager(memory=memory)
        return cls(cfg, agent, memory, tool_registry, sessions)

    # ---------------- 业务动作 ----------------
    def chat(self, query: str, session_id: Optional[str] = None) -> ChatResponse:
        """执行一次对话：会话 → Agent 运行 → 更新元数据 → 响应。"""
        session = self.sessions.get_or_create(session_id)
        result = self.agent.run(query, session_id=session.session_id)
        self.sessions.touch(session.session_id)
        return ChatResponse(
            session_id=session.session_id,
            answer=result.answer,
            success=result.success,
            steps_taken=result.steps_taken,
            trace=[
                TraceItem(
                    step_id=t.step_id,
                    action=t.action,
                    args=t.args,
                    observation=t.observation,
                    status=t.status,
                )
                for t in result.trace
            ],
        )

    def list_tools(self) -> ToolsResponse:
        schemas = list_tool_schemas(self.tool_registry)
        return ToolsResponse(
            tools=[
                ToolSchemaOut(
                    name=s.name,
                    description=s.description,
                    parameters=s.parameters,
                )
                for s in schemas
            ]
        )

    def list_sessions(self) -> List[SessionItem]:
        return [
            SessionItem(
                session_id=s.session_id,
                created_at=s.created_at,
                last_active=s.last_active,
                message_count=s.message_count,
            )
            for s in self.sessions.list()
        ]

    def delete_session(self, session_id: str) -> bool:
        return self.sessions.delete(session_id)

    def health(self) -> HealthResponse:
        app_cfg = self.config.get("app", {})
        return HealthResponse(
            status="ok",
            app=app_cfg.get("name", "agent_framework"),
            version=app_cfg.get("version", "0.0.0"),
            enabled_tools=list(self.tool_registry.names),
        )

    def system_info(self) -> SystemInfoResponse:
        app_cfg = self.config.get("app", {})
        return SystemInfoResponse(
            app=app_cfg.get("name", "agent_framework"),
            version=app_cfg.get("version", "0.0.0"),
            llm_provider=self.config.get("llm", {}).get("provider", "fake"),
            memory_provider=self.config.get("memory", {}).get("provider", "in_memory"),
            planner_provider=self.config.get("planner", {}).get("provider", "llm"),
            agent_provider=self.config.get("agent", {}).get("provider", "react"),
            enabled_tools=list(self.tool_registry.names),
            active_sessions=len(self.sessions),
        )
