"""时间工具：获取当前日期时间，支持 strftime 自定义格式。"""
import datetime

from src.tool.base import BaseTool, ToolSchema
from src.tool.registry import tool_registry


@tool_registry.register("time")
class TimeTool(BaseTool):
    """当前时间工具。"""

    @property
    def tool_schema(self) -> ToolSchema:
        return ToolSchema(
            name="time",
            description="获取当前日期和时间，支持自定义 strftime 格式，返回格式化字符串与时间戳。",
            parameters={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "strftime 格式，如 '%Y-%m-%d %H:%M:%S'、'%Y年%m月%d日'",
                        "default": "%Y-%m-%d %H:%M:%S",
                    }
                },
            },
        )

    def run(self, format: str = "%Y-%m-%d %H:%M:%S") -> dict:
        now = datetime.datetime.now()
        return {
            "datetime": now.strftime(format),
            "timestamp": int(now.timestamp()),
        }
