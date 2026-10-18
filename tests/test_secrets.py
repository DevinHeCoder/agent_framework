"""P0-3 密钥管理测试：生产 fail-fast + 日志脱敏。"""
import logging

import pytest

from src.common.exceptions import ConfigError
from src.common.security import PLACEHOLDER_API_KEYS, redact_secrets, validate_runtime_security
from src.utils.config_loader import load_config
from src.utils.logger import RedactingFormatter


# ---------------- 脱敏 ----------------
def test_redact_sk_key():
    raw = "请求参数: sk-abcdefghijklmn123456 结束"
    out = redact_secrets(raw)
    assert "sk-***" in out
    assert "sk-abcdefghijklmn123456" not in out


def test_redact_bearer_token():
    raw = 'Authorization: Bearer abcdef1234567890XYZ'
    out = redact_secrets(raw)
    assert "Bearer ***" in out
    assert "abcdef1234567890XYZ" not in out


def test_redact_key_value_pair():
    out = redact_secrets('AGENT_LLM_API_KEY=sk-abcdef123456; x=1')
    assert "sk-abcdef123456" not in out
    assert "api_key=***" in out.lower() or "AGENT_LLM_API_KEY=***" in out


def test_redact_no_false_positive():
    text = "普通文本 sk 前缀词不会误伤：请求正常完成"
    assert redact_secrets(text) == text


def test_redacting_formatter_used():
    """RedactingFormatter 格式化后输出不含明文密钥。"""
    fmt = RedactingFormatter("%(levelname)s | %(message)s")
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "key=sk-abcdefghijklmn123456", None, None
    )
    out = fmt.format(record)
    assert "sk-abcdefghijklmn123456" not in out
    assert "sk-***" in out


# ---------------- 生产 fail-fast ----------------
def test_production_empty_key_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_APP_ENV", "production")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "")
    cfg = load_config()
    assert cfg["app"]["env"] == "production"
    with pytest.raises(ConfigError):
        validate_runtime_security(cfg)


def test_production_placeholder_key_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_APP_ENV", "production")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-你的百炼APIKey")
    cfg = load_config()
    with pytest.raises(ConfigError):
        validate_runtime_security(cfg)


def test_production_valid_key_passes(monkeypatch):
    monkeypatch.setenv("AGENT_APP_ENV", "production")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-real-abcdefghijklmn1234567890")
    cfg = load_config()
    # 不抛异常即通过
    validate_runtime_security(cfg)


def test_development_without_key_allowed(monkeypatch):
    """默认 development：即使无 key 也不阻断（本地演示/测试）。"""
    monkeypatch.setenv("AGENT_APP_ENV", "development")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "")
    cfg = load_config()
    validate_runtime_security(cfg)  # 不抛


def test_fake_provider_not_blocked_in_production(monkeypatch):
    """production + fake provider（演示模式）不要求真实 key。"""
    monkeypatch.setenv("AGENT_APP_ENV", "production")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "")
    cfg = load_config()
    validate_runtime_security(cfg)  # 不抛
