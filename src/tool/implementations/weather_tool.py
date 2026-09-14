"""天气工具：内置 mock 数据（可插拔），后续可按同接口替换为真实天气 API 实现。

说明：当前返回的为演示用 mock 数据，结果中携带 "source": "mock" 标记，
避免误导为真实天气。
"""
from src.tool.base import BaseTool, ToolSchema
from src.tool.registry import tool_registry

_MOCK_WEATHER = {
    "北京": {"temperature": 24, "condition": "晴", "humidity": 45},
    "上海": {"temperature": 27, "condition": "多云", "humidity": 70},
    "广州": {"temperature": 30, "condition": "阵雨", "humidity": 82},
    "深圳": {"temperature": 29, "condition": "多云", "humidity": 78},
    "杭州": {"temperature": 26, "condition": "小雨", "humidity": 75},
    "成都": {"temperature": 23, "condition": "阴", "humidity": 68},
    "武汉": {"temperature": 28, "condition": "晴", "humidity": 60},
}


@tool_registry.register("weather")
class WeatherTool(BaseTool):
    """天气查询工具（mock 实现）。"""

    @property
    def tool_schema(self) -> ToolSchema:
        return ToolSchema(
            name="weather",
            description=(
                "查询指定城市的当前天气（温度、天气状况、湿度）。"
                "注意：当前返回 mock 演示数据，非实时真实天气。"
            ),
            parameters={
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 '北京'、'上海'",
                    }
                },
            },
        )

    def run(self, city: str) -> dict:
        info = _MOCK_WEATHER.get(city)
        if info is None:
            return {
                "city": city,
                "note": f"暂无城市 '{city}' 的 mock 数据，可用城市: {list(_MOCK_WEATHER)}",
                "source": "mock",
            }
        return {
            "city": city,
            "temperature": info["temperature"],
            "condition": info["condition"],
            "humidity": info["humidity"],
            "unit": "celsius",
            "source": "mock",
        }
