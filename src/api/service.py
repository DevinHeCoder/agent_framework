"""P5 API 层：业务服务（组装各层 + 暴露给路由的纯逻辑）。"""
from __future__ import annotations

from typing import List, Optional

from src.agent import build_agent
from src.api.schemas import (
    BrandingInfo,
    ChatResponse,
    HealthResponse,
    MessageItem,
    SessionItem,
    SessionMessagesResponse,
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

    def __init__(self, config, agent, memory, tool_registry, sessions, llm=None):
        self.config = config
        self.agent = agent
        self.memory = memory
        self.tool_registry = tool_registry
        self.sessions = sessions
        self.llm = llm

    # ---------------- 组装 ----------------
    @classmethod
    def build_from_config(
        cls,
        config=None,
        *,
        llm: Optional[LLMClient] = None,
        usage=None,
    ) -> "AgentService":
        """按配置一次性组装全部层（可注入 llm / usage 便于测试/演示）。"""
        cfg = config or load_config()
        tool_cfg = cfg.get("tool", {})
        enabled_tools = tool_cfg.get("enabled")

        tool_registry = build_tool_registry(enabled=enabled_tools)
        memory = build_memory(cfg.get("memory"))
        llm = llm or build_llm_client(cfg.get("llm"))
        if usage is not None and hasattr(llm, "set_usage_sink"):
            llm.set_usage_sink(usage)
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
        return cls(cfg, agent, memory, tool_registry, sessions, llm=llm)

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

    def get_session_messages(self, session_id: str) -> SessionMessagesResponse:
        """读取会话历史消息（来自记忆层，按时间顺序）。"""
        messages = self.memory.get_messages(session_id)
        return SessionMessagesResponse(
            session_id=session_id,
            messages=[
                MessageItem(role=m.role, content=m.content) for m in messages
            ],
        )

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

    def readiness(self) -> dict:
        """就绪探针：逐个检查依赖，任一失败返回 not_ready（禁止探针自身抛 500）。"""
        checks: dict = {}
        ok = True

        # 配置已加载（能走到这里即已加载）
        checks["config"] = {"ok": True}

        # Redis：仅当选型为 redis / hybrid 时必查
        mem_cfg = self.config.get("memory", {}) or {}
        mem_provider = str(mem_cfg.get("provider", "in_memory")).lower()
        if mem_provider in ("redis", "hybrid"):
            checks["redis"] = self._check_redis()
            ok &= bool(checks["redis"]["ok"])
        else:
            checks["redis"] = {"ok": True, "note": "not_used"}

        # LLM client 已初始化（fake 演示模式同样视为就绪）
        checks["llm"] = {"ok": self.llm is not None}
        ok &= bool(checks["llm"]["ok"])

        return {"status": "ready" if ok else "not_ready", "checks": checks}

    def _check_redis(self) -> dict:
        """内存/Redis 记忆的连通性检查。"""
        try:
            client = getattr(self.memory, "_client", None)
            if client is None:
                return {"ok": False, "error": "memory provider 未初始化 redis 客户端"}
            client.ping()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 - 探针禁止抛错
            return {"ok": False, "error": str(e)}

    def system_info(self) -> SystemInfoResponse:
        app_cfg = self.config.get("app", {})
        auth_cfg = self.config.get("server", {}).get("auth", {})
        brand_cfg = self.config.get("branding", {}) or {}
        return SystemInfoResponse(
            app=app_cfg.get("name", "agent_framework"),
            version=app_cfg.get("version", "0.0.0"),
            llm_provider=self.config.get("llm", {}).get("provider", "fake"),
            memory_provider=self.config.get("memory", {}).get("provider", "in_memory"),
            planner_provider=self.config.get("planner", {}).get("provider", "llm"),
            agent_provider=self.config.get("agent", {}).get("provider", "react"),
            enabled_tools=list(self.tool_registry.names),
            active_sessions=len(self.sessions),
            auth_required=_to_bool(auth_cfg.get("enabled", False)),
            branding=BrandingInfo(
                app_name=str(brand_cfg.get("app_name") or BrandingInfo().app_name),
                logo_text=str(brand_cfg.get("logo_text") or BrandingInfo().logo_text),
                logo_suffix=str(brand_cfg.get("logo_suffix") or BrandingInfo().logo_suffix),
                agent_label=str(brand_cfg.get("agent_label") or BrandingInfo().agent_label),
                primary_color=str(brand_cfg.get("primary_color") or BrandingInfo().primary_color),
                accent_color=str(brand_cfg.get("accent_color") or BrandingInfo().accent_color),
            ),
        )



def _to_bool(value: object) -> bool:
    """布尔规范化：兼容 YAML 占位符默认值返回的字符串。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)
