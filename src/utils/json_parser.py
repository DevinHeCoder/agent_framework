"""
LLM 输出 JSON 容错清洗。

真实工程无法假设 LLM 永远输出合法 JSON——可能带 ```json 标记、前后缀文字、
多余换行、BOM 等。本模块提供逐级降级的解析策略：
    1. 直接 json.loads
    2. 剥离 markdown ```json ``` 围栏
    3. 截取首个 { ... 最后一个 } 的子串再解析
全部失败返回 None，交由上层重试/兜底。
"""
from __future__ import annotations

import json
from typing import Any, Optional


def try_parse_json(text: str) -> Optional[dict]:
    """容错解析 JSON 对象，失败返回 None（不抛异常）。

    参数:
        text: LLM 原始输出文本
    返回:
        解析成功的 dict，或 None
    """
    if not text or not isinstance(text, str):
        return None

    candidates = _candidate_texts(text)
    for cand in candidates:
        parsed = _parse_single(cand)
        if isinstance(parsed, dict):
            return parsed
    return None


def try_parse_json_strict(text: str) -> Optional[Any]:
    """更宽松的解析：不要求顶层是 dict，返回任意 JSON 值（list/str/...）。"""
    if not text or not isinstance(text, str):
        return None
    for cand in _candidate_texts(text):
        parsed = _parse_single(cand)
        if parsed is not None:
            return parsed
    return None


def extract_json_blocks(text: str) -> list[str]:
    """抽取文本中所有 ```json ... ``` 代码块内容（用于多段输出场景）。"""
    import re

    pattern = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
    return [m.group(1).strip() for m in pattern.finditer(text)]


# ---------------- 内部实现 ----------------
def _candidate_texts(text: str) -> list[str]:
    """按优先级生成候选文本：原样 → 去围栏 → 截取首尾大括号。"""
    candidates: list[str] = []
    stripped = text.strip()
    if stripped.startswith("\ufeff"):  # 去 BOM
        stripped = stripped[1:].strip()
    candidates.append(stripped)

    # 剥离 markdown 围栏
    if stripped.startswith("```"):
        body = stripped
        for marker in ("```json", "```JSON", "```"):
            if body.startswith(marker):
                body = body[len(marker):]
                break
        if body.endswith("```"):
            body = body[:-3]
        body = body.strip()
        candidates.append(body)

    # 截取首个 { 到最后一个 }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start:end + 1])

    return candidates


def _parse_single(cand: str) -> Optional[Any]:
    try:
        return json.loads(cand)
    except (json.JSONDecodeError, ValueError):
        return None
