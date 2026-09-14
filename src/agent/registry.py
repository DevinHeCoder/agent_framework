"""agent 层的可插拔注册表实例。"""
from src.agent.base import BaseAgent
from src.common.registry import Registry

agent_registry = Registry(
    name="agent",
    base_type=BaseAgent,
)
