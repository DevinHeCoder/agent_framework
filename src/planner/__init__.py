"""
planner 包：统一任务规划入口（LLM 任务拆解，按配置选型）。

用法::

    from src.planner import build_planner
    planner = build_planner(cfg.get("planner"), llm=llm)
    plan = planner.plan("帮我查杭州天气并算一下 3*8", tools=tool_schemas)

配置选型（config/settings.yaml 的 planner 段）:
    provider: llm           （当前唯一实现；llm= 注入 LLMClient 实例）
    max_steps: 6            （单次任务最大规划步数）
"""
from __future__ import annotations

from typing import Optional

from src.llm_client.base import LLMClient
from src.planner.base import BasePlanner, Plan, Step
from src.planner.llm_planner import LLMPlanner
from src.planner.registry import planner_registry

__all__ = [
    "BasePlanner",
    "Plan",
    "Step",
    "planner_registry",
    "build_planner",
    "LLMPlanner",
]


def build_planner(
    config: Optional[dict] = None,
    *,
    llm: LLMClient,
) -> BasePlanner:
    """按配置构建规划器实例。

    参数:
        config: planner 配置段；缺省按 llm 构建。
        llm: 注入的 LLM 客户端（规划依赖 LLM）。
    """
    cfg = config or {}
    provider = cfg.get("provider", "llm")
    return planner_registry.create(
        provider,
        llm=llm,
        max_steps=cfg.get("max_steps", 6),
        parse_retries=cfg.get("parse_retries", 2),
        # 性能优化：规划模型可独立于主模型（如用 flash 规划、max 回答）
        plan_model=cfg.get("plan_model"),
    )
