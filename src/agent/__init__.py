"""
agent 包：统一 Agent 入口（按配置选型）。

用法::

    from src.agent import build_agent
    agent = build_agent(
        cfg.get("agent"),
        llm=llm, memory=memory, planner=planner,
        tool_registry=tool_registry, tool_config=cfg.get("tool"),
    )
    result = agent.run("帮我查杭州天气")

配置选型（config/settings.yaml 的 agent / tool 段）:
    agent.provider: react
    agent.max_loop: 5 / json_parse_retries: 2
    tool.retry / tool.param_fix_attempts → 注入 RetryPolicy
"""
from __future__ import annotations

from typing import Optional

from src.agent.base import AgentResult, BaseAgent, TraceEntry
from src.agent.policy import RetryPolicy
from src.agent.react_agent import ReactAgent
from src.agent.registry import agent_registry
from src.llm_client.base import LLMClient
from src.memory.base import BaseMemory
from src.planner.base import BasePlanner

__all__ = [
    "BaseAgent",
    "AgentResult",
    "TraceEntry",
    "RetryPolicy",
    "agent_registry",
    "build_agent",
    "ReactAgent",
]


def build_agent(
    config: Optional[dict] = None,
    *,
    llm: LLMClient,
    memory: BaseMemory,
    planner: BasePlanner,
    tool_registry,
    tool_config: Optional[dict] = None,
    enabled_tools: Optional[list] = None,
) -> BaseAgent:
    """按配置构建 Agent 实例。

    参数:
        config: agent 配置段；缺省按 react 构建。
        llm / memory / planner / tool_registry: 注入的各层实例。
        tool_config: tool 配置段（retry / param_fix_attempts → RetryPolicy）。
        enabled_tools: 暴露给 Agent 的工具白名单（缺省为全部已注册）。
    """
    cfg = config or {}
    tc = tool_config or {}
    policy = RetryPolicy(
        max_retries=tc.get("retry", 2),
        param_fix_attempts=tc.get("param_fix_attempts", 2),
    )
    provider = cfg.get("provider", "react")
    return agent_registry.create(
        provider,
        llm=llm,
        memory=memory,
        planner=planner,
        tool_registry=tool_registry,
        policy=policy,
        max_loop=cfg.get("max_loop", 5),
        json_parse_retries=cfg.get("json_parse_retries", 2),
        enabled_tools=enabled_tools,
    )
