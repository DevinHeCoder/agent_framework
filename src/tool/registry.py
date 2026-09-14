"""tool 层的可插拔注册表实例。"""
from src.common.registry import Registry
from src.tool.base import BaseTool

tool_registry = Registry(
    name="tool",
    base_type=BaseTool,
)
