"""
轻量参数校验器：基于 JSON Schema 子集校验工具参数（自研，零外部依赖）。

支持的 JSON Schema 关键字子集：
  - 顶层: type(object) / required / properties
  - 字段: type / description / default / enum
          minimum / maximum（number/integer）
          min_length / max_length（string）
          items（array 元素类型）

不支持的复杂关键字（$ref / oneOf / allOf / pattern…）会被忽略，不会误拒绝；
若需完整标准校验，可后续无缝替换为 jsonschema 库（validate_args 签名不变）。

异常语义（供 Agent 参数自愈策略识别）：
  - 校验失败抛 ToolParamError，上层可把结构化错误回喂 LLM 重新生成参数。
"""
from __future__ import annotations

from typing import Any, Dict

from src.common.exceptions import ToolParamError


def validate_args(parameters: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """按参数声明校验并归一化工具参数。

    参数:
        parameters: 工具声明的 JSON Schema（parameters 字段）
        args: LLM 生成的原始参数字典
    返回:
        归一化后的参数（含 default 填充）
    异常:
        ToolParamError: 参数不是 dict / 缺少必填 / 类型或约束不满足
    """
    if not isinstance(parameters, dict):
        return dict(args or {})

    if not isinstance(args, dict):
        raise ToolParamError(f"参数必须是对象（dict），实际为 {type(args).__name__}")

    required = parameters.get("required", [])
    properties = parameters.get("properties", {})

    # 1. 必填检查
    for field in required:
        if field not in args:
            raise ToolParamError(f"缺少必填参数 '{field}'（需要: {required}）")

    # 2. 类型 / 约束检查 + default 填充
    result: Dict[str, Any] = dict(args)
    for field, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        if field not in result:
            if "default" in spec:
                result[field] = spec["default"]
            continue
        _check_field(field, spec, result[field])

    return result


# ---------------- 内部实现 ----------------
def _check_field(field: str, spec: Dict[str, Any], value: Any) -> None:
    """单字段校验：类型 → enum → 数值范围 → 字符串长度 → 数组元素。"""
    expected = spec.get("type")
    if expected:
        _check_type(field, expected, value)

    enum = spec.get("enum")
    if enum is not None and value not in enum:
        raise ToolParamError(f"参数 '{field}' 取值 {value!r} 不在允许集合 {enum}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            raise ToolParamError(
                f"参数 '{field}' = {value} 小于最小值 {spec['minimum']}"
            )
        if "maximum" in spec and value > spec["maximum"]:
            raise ToolParamError(
                f"参数 '{field}' = {value} 大于最大值 {spec['maximum']}"
            )

    if isinstance(value, str):
        if "min_length" in spec and len(value) < spec["min_length"]:
            raise ToolParamError(
                f"参数 '{field}' 长度 {len(value)} 小于最小长度 {spec['min_length']}"
            )
        if "max_length" in spec and len(value) > spec["max_length"]:
            raise ToolParamError(
                f"参数 '{field}' 长度 {len(value)} 大于最大长度 {spec['max_length']}"
            )

    if isinstance(value, list) and "items" in spec:
        item_type = spec["items"].get("type") if isinstance(spec["items"], dict) else None
        for i, item in enumerate(value):
            if item_type:
                _check_type(f"{field}[{i}]", item_type, item)


def _check_type(field: str, expected: Any, value: Any) -> None:
    """类型校验；expected 支持 'string' 或 ['string','integer'] 等。"""
    if isinstance(expected, str):
        types = [expected]
    elif isinstance(expected, list):
        types = list(expected)
    else:
        return

    def _matches(t: str) -> bool:
        if t == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if t == "string":
            return isinstance(value, str)
        if t == "boolean":
            return isinstance(value, bool)
        if t == "array":
            return isinstance(value, list)
        if t == "object":
            return isinstance(value, dict)
        if t == "null":
            return value is None
        return True  # 未知类型不拒绝

    if not any(_matches(t) for t in types):
        raise ToolParamError(
            f"参数 '{field}' 类型错误：期望 {expected}，实际 {type(value).__name__}（{value!r}）"
        )
