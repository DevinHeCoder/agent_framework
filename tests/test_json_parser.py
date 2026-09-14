"""P0 LLM 输出 JSON 容错解析单测。"""
from src.utils.json_parser import (
    extract_json_blocks,
    try_parse_json,
    try_parse_json_strict,
)


def test_direct_json():
    assert try_parse_json('{"a": 1}') == {"a": 1}


def test_markdown_fence():
    assert try_parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_surrounding_text():
    """前导 / 后缀文字应被截取首尾大括号逻辑处理。"""
    text = '好的，结果如下：\n{"finish": true, "answer": "x"}\n完毕'
    assert try_parse_json(text) == {"finish": True, "answer": "x"}


def test_bom():
    assert try_parse_json('\ufeff{"a": 1}') == {"a": 1}


def test_invalid_returns_none():
    assert try_parse_json("这不是 JSON") is None
    assert try_parse_json("") is None
    assert try_parse_json(None) is None


def test_strict_returns_any_json():
    assert try_parse_json_strict("[1, 2, 3]") == [1, 2, 3]
    assert try_parse_json_strict('"str"') == "str"


def test_extract_blocks():
    text = 'a\n```json\n{"x":1}\n```\nb\n```json\n{"y":2}\n```'
    blocks = extract_json_blocks(text)
    assert len(blocks) == 2
    assert try_parse_json(blocks[0]) == {"x": 1}
    assert try_parse_json(blocks[1]) == {"y": 2}
