"""P0 配置加载单测：YAML 加载、${ENV} 展开、深合并、点路径、环境变量覆盖、.env 自动加载。"""
import os

import pytest

from src.common.exceptions import ConfigError
from src.utils.config_loader import (
    deep_merge,
    expand_env,
    get_path,
    load_config,
    load_dotenv,
    load_yaml,
)


# ---------------- load_yaml ----------------
def test_load_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("a: 1\nb:\n  c: x\n", encoding="utf-8")
    assert load_yaml(p) == {"a": 1, "b": {"c": "x"}}


def test_load_yaml_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    assert load_yaml(p) == {}


def test_load_yaml_missing():
    with pytest.raises(ConfigError):
        load_yaml("no_such_file.yaml")


def test_load_yaml_bad_root(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")  # 根节点是 list
    with pytest.raises(ConfigError):
        load_yaml(p)


# ---------------- expand_env ----------------
def test_expand_env(monkeypatch):
    monkeypatch.setenv("AGENT_X", "hello")
    assert expand_env("${AGENT_X}") == "hello"
    assert expand_env("${AGENT_NOT_SET:default}") == "default"
    assert expand_env({"k": ["${AGENT_X}"]}) == {"k": ["hello"]}


def test_expand_env_missing_raises(monkeypatch):
    monkeypatch.delenv("AGENT_NOT_SET", raising=False)
    with pytest.raises(ConfigError):
        expand_env("${AGENT_NOT_SET}")


# ---------------- deep_merge ----------------
def test_deep_merge():
    base = {"a": 1, "b": {"x": 1, "y": 2}}
    override = {"b": {"y": 9, "z": 3}, "c": 4}
    assert deep_merge(base, override) == {
        "a": 1,
        "b": {"x": 1, "y": 9, "z": 3},
        "c": 4,
    }
    # 不修改入参
    assert base == {"a": 1, "b": {"x": 1, "y": 2}}


# ---------------- get_path ----------------
def test_get_path():
    cfg = {"llm": {"model": "x"}}
    assert get_path(cfg, "llm.model") == "x"
    assert get_path(cfg, "llm.api_key", "d") == "d"
    assert get_path(cfg, "no.such", "d") == "d"


# ---------------- load_config 完整链路 ----------------
def test_load_config_full_flow(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text(
        "app:\n  name: agent_framework\nllm:\n  model: ${AGENT_MODEL:gpt}\n",
        encoding="utf-8",
    )
    # 环境变量深路径覆盖：AGENT_LLM__TEMPERATURE=0.5 -> cfg['llm']['temperature']
    monkeypatch.setenv("AGENT_LLM__TEMPERATURE", "0.5")

    cfg = load_config(p)
    assert cfg["app"]["name"] == "agent_framework"
    assert cfg["llm"]["model"] == "gpt"        # ${ENV:default} 展开
    assert cfg["llm"]["temperature"] == 0.5    # 环境变量覆盖 + 数值 coerce


def test_load_config_env_override_bool(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text("agent:\n  max_loop: 5\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_AGENT__MAX_LOOP", "true")
    cfg = load_config(p)
    assert cfg["agent"]["max_loop"] is True


# ---------------- load_dotenv 轻量加载 ----------------
def _write_dotenv(tmp_path, content: str):
    p = tmp_path / ".env"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_dotenv_basic(tmp_path, monkeypatch):
    monkeypatch.delenv("DOT_X", raising=False)
    monkeypatch.delenv("DOT_Y", raising=False)
    load_dotenv(_write_dotenv(tmp_path, "DOT_X=hello\nDOT_Y=world\n"))
    assert os.environ.get("DOT_X") == "hello"
    assert os.environ.get("DOT_Y") == "world"


def test_load_dotenv_quotes_comments_and_garbage(tmp_path, monkeypatch):
    for k in ("DOT_Q", "DOT_S", "DOT_BAD"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(_write_dotenv(
        tmp_path,
        "# 注释行\n\n"
        'DOT_Q="double quote"\n'
        "DOT_S='single'\n"
        "NOT_AN_ASSIGNMENT\n"
        "123BAD=skip\n"
        "=no-key\n"
    ))
    assert os.environ.get("DOT_Q") == "double quote"
    assert os.environ.get("DOT_S") == "single"
    assert os.environ.get("NOT_AN_ASSIGNMENT") is None
    assert os.environ.get("123BAD") is None


def test_load_dotenv_does_not_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("DOT_KEEP", "from_env")
    load_dotenv(_write_dotenv(tmp_path, "DOT_KEEP=from_dotenv\n"))
    assert os.environ.get("DOT_KEEP") == "from_env"


def test_load_dotenv_missing_file(tmp_path, monkeypatch):
    load_dotenv(tmp_path / "no_such.env")  # 不应抛异常


def test_load_config_reads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    env_file = _write_dotenv(tmp_path, "AGENT_MODEL=qwen3-max\n")
    p = tmp_path / "settings.yaml"
    p.write_text("llm:\n  model: ${AGENT_MODEL:gpt}\n", encoding="utf-8")
    cfg = load_config(p, dotenv_path=env_file)
    assert cfg["llm"]["model"] == "qwen3-max"   # ${ENV} 展开命中 .env 值


def test_load_config_env_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "from_real_env")
    env_file = _write_dotenv(tmp_path, "AGENT_MODEL=qwen3-max\n")
    p = tmp_path / "settings.yaml"
    p.write_text("llm:\n  model: ${AGENT_MODEL:gpt}\n", encoding="utf-8")
    cfg = load_config(p, dotenv_path=env_file)
    assert cfg["llm"]["model"] == "from_real_env"
