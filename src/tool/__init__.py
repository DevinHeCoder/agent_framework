"""
tool 包：统一工具入口（可插拔注册中心 + 参数校验 + 执行兜底）。

用法::

    from src.tool import build_tool_registry, run_tool
    reg = build_tool_registry()
    result = run_tool(reg, "calc", {"expression": "(3+5)*2"})
    print(result.content)   # 供 LLM 回填的可读结果

异常语义（供 Agent 兜底策略识别）：
  - ToolNotFoundError：工具不存在 → 引导 LLM 换工具
  - ToolParamError：参数校验失败 → 回喂 LLM 重新生成参数
  - ToolExecutionError：执行期异常 → 重试或兜底
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.common.exceptions import (
    RegistryError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolParamError,
)
from src.tool.base import BaseTool, ToolResult, ToolSchema
from src.tool.registry import tool_registry
from src.tool.validator import validate_args

# 导入实现以触发 @register 装饰器注册（必须在 registry 定义之后）
from src.tool.implementations import calc_tool  # noqa: F401,E402
from src.tool.implementations import kb_search_tool  # noqa: F401,E402
from src.tool.implementations import time_tool  # noqa: F401,E402
from src.tool.implementations import weather_tool  # noqa: F401,E402

__all__ = [
    "BaseTool",
    "ToolSchema",
    "ToolResult",
    "tool_registry",
    "build_tool_registry",
    "run_tool",
    "list_tool_schemas",
]


def list_tool_schemas(
    registry,
    enabled: Optional[List[str]] = None,
) -> List[ToolSchema]:
    """返回工具的 schema 列表（供 Planner 暴露可用工具给 LLM）。

    参数:
        registry: 工具注册表
        enabled: 可选，只返回指定工具；缺省返回全部已注册工具。
    """
    names = list(enabled) if enabled is not None else list(registry.names)
    schemas: List[ToolSchema] = []
    for name in names:
        if not registry.has(name):
            continue
        try:
            instance = registry.create(name)
        except Exception:
            continue
        try:
            schema = instance.tool_schema
        except Exception:
            continue
        schemas.append(schema)
    return schemas


def build_tool_registry(enabled: Optional[List[str]] = None) -> "Registry":
    """返回工具注册表（所有实现已通过 import 自动注册）。

    参数:
        enabled: 可选，只允许指定工具名被使用；有未注册的名字时抛 ToolNotFoundError。
    """
    if enabled is not None:
        missing = [n for n in enabled if not tool_registry.has(n)]
        if missing:
            raise ToolNotFoundError(f"配置启用的工具未注册: {missing}")
    return tool_registry


def run_tool(
    registry,
    name: str,
    args: Optional[Dict[str, Any]] = None,
    **tool_init_kwargs: Any,
) -> ToolResult:
    """统一工具执行入口：参数校验 → 实例化 → 执行 → 结果封装。

    参数:
        registry: 工具注册表（build_tool_registry() 的返回值）
        name: 工具名
        args: 工具执行参数（LLM 生成）
        tool_init_kwargs: 透传给工具构造函数的参数（如 top_k 等配置）
    返回:
        ToolResult（ok / content / data / error）
    异常:
        按上述语义抛 ToolNotFoundError / ToolParamError / ToolExecutionError
    """
    args = dict(args or {})

    # 1. 取工具类（不存在 → 引导换工具）
    try:
        cls = registry.get(name)
    except RegistryError as e:
        raise ToolNotFoundError(str(e)) from e

    # 2. 实例化（构造参数透传，如 top_k 等配置）
    try:
        instance = registry.create(name, **tool_init_kwargs)
    except RegistryError as e:
        raise ToolExecutionError(f"工具 '{name}' 实例化失败: {e}") from e

    # 3. 参数校验（失败 → 可自愈）。注意取实例属性，而非类属性。
    try:
        schema = instance.tool_schema
    except Exception:
        schema = None
    if schema is not None:
        args = validate_args(schema.parameters, args)

    # 4. 执行
    try:
        data = instance.run(**args)
    except ToolError:
        raise
    except Exception as e:
        raise ToolExecutionError(f"工具 '{name}' 执行异常: {e}") from e

    return ToolResult(ok=True, content=_render_content(name, data), data=data)


def _render_content(name: str, data: Any) -> str:
    """把工具结构化结果渲染为可读文本（回填 LLM）。"""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(data)
