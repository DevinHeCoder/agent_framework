"""planner 层的可插拔注册表实例。"""
from src.common.registry import Registry
from src.planner.base import BasePlanner

planner_registry = Registry(
    name="planner",
    base_type=BasePlanner,
)
