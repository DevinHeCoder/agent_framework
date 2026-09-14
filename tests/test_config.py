"""P0 配置加载单测：YAML 加载、${ENV} 展开、深合并、点路径、环境变量覆盖。"""
import pytest

from src.common.exceptions import ConfigError
from src.utils.config_loader import (
    deep_merge,
    expand_env,
    get_path,
    load_config,
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
