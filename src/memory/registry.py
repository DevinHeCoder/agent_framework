"""memory 层的可插拔注册表实例。"""
from src.common.registry import Registry
from src.memory.base import BaseMemory

memory_registry = Registry(
    name="memory",
    base_type=BaseMemory,
)
