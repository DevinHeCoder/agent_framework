"""安全计算器：ast 白名单求值，禁用 eval。

仅允许：数字常量、四则/整除/取余/幂运算、一元正负、括号、
以及白名单函数（abs / round / min / max / pow / sqrt）。
"""
import ast
import math
import operator
from typing import Any

from src.common.exceptions import ToolExecutionError
from src.tool.base import BaseTool, ToolSchema
from src.tool.registry import tool_registry

# 允许的二元 / 一元运算
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
# 允许调用的函数白名单
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "sqrt": math.sqrt,
}


@tool_registry.register("calc")
class CalcTool(BaseTool):
    """安全计算器工具。"""

    @property
    def tool_schema(self) -> ToolSchema:
        return ToolSchema(
            name="calc",
            description=(
                "安全计算器：执行四则运算、整除、取余、幂、绝对值、"
                "min/max/round/sqrt 等数学表达式，返回计算结果。"
            ),
            parameters={
                "type": "object",
                "required": ["expression"],
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '(3+5)*2'、'2**10'、'abs(-8)'、'sqrt(16)'",
                    }
                },
            },
        )

    def run(self, expression: str) -> dict:
        try:
            value = self._safe_eval(expression)
        except ToolExecutionError:
            raise
        except Exception as e:  # 词法/语法/类型错误统一包装
            raise ToolExecutionError(f"表达式计算失败: {e}") from e
        return {"expression": expression, "result": value}

    # ---------------- 内部：ast 白名单求值 ----------------
    def _safe_eval(self, expr: str) -> Any:
        tree = ast.parse(expr, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise TypeError("仅支持数字常量")
        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if op is None:
                raise TypeError(f"不支持的运算符: {type(node.op).__name__}")
            return op(self._eval_node(node.left), self._eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _UNARY_OPS.get(type(node.op))
            if op is None:
                raise TypeError(f"不支持的一元运算符: {type(node.op).__name__}")
            return op(self._eval_node(node.operand))
        if isinstance(node, ast.Call):
            func_name = getattr(node.func, "id", None)
            func = _ALLOWED_FUNCS.get(func_name)
            if func is None:
                raise TypeError(
                    f"调用未知函数 '{func_name}'，仅允许: {', '.join(sorted(_ALLOWED_FUNCS))}"
                )
            args = [self._eval_node(a) for a in node.args]
            return func(*args)
        raise TypeError(f"不支持的表达式节点: {type(node).__name__}")
