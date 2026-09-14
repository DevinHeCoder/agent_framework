"""
工具抽象基类：所有工具实现统一接口，供 LLM 选型与参数校验使用。

- ToolSchema：工具的 JSON Schema 描述（name / description / parameters）
- ToolResult：统一执行结果（可读 content 回填 LLM + 结构化 data）
- BaseTool：工具基类，实现类只需声明 tool_schema 与 run
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolSchema:
    """工具描述：name + description + parameters（JSON Schema 形态）。"""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """统一工具执行结果。

    属性:
        ok: 是否成功
        content: 供 LLM 回填的可读文本（如 "结果 = 16"）
        data: 结构化结果（原始返回值）
        error: 失败时的错误信息
    """

    ok: bool
    content: str
    data: Any = None
    error: Optional[str] = None


class BaseTool(ABC):
    """工具基类。实现类继承后实现 tool_schema 与 run，并用 @register 注册。"""

    @property
    @abstractmethod
    def tool_schema(self) -> ToolSchema:
        """返回工具描述（含参数 JSON Schema），供 LLM 与校验器使用。"""
        pass

    @abstractmethod
    def run(self, **kwargs) -> Any:
        """执行工具逻辑，返回结构化结果（dict/list 等）。"""
        pass
