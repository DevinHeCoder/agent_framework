"""P0 日志单测：setup_logging 幂等、get_logger 返回命名 Logger、配置缺失回退。"""
import logging

import pytest

from src.utils.logger import get_logger, setup_logging


def test_get_logger_returns_logger():
    lg = get_logger("agent_framework.test")
    assert isinstance(lg, logging.Logger)
    assert lg.name == "agent_framework.test"


def test_setup_logging_idempotent():
    setup_logging()          # 第一次
    setup_logging()          # 幂等，不报错


def test_setup_logging_force_reload(tmp_path):
    setup_logging(force=True)  # 强制重载也不报错


def test_get_logger_config_missing_fallback(tmp_path, monkeypatch):
    """配置文件缺失时回退基础配置，不抛异常。"""
    import src.utils.logger as logger_mod

    monkeypatch.setattr(logger_mod, "_configured", False)
    monkeypatch.setattr(
        logger_mod, "DEFAULT_LOGGING_CONFIG_PATH", tmp_path / "nope.yaml"
    )
    lg = logger_mod.get_logger("agent_framework.fallback")
    assert isinstance(lg, logging.Logger)


def test_setup_logging_missing_config_raises(tmp_path):
    from src.common.exceptions import ConfigError
    from src.utils import logger as logger_mod

    with pytest.raises(ConfigError):
        logger_mod.setup_logging(tmp_path / "nope.yaml", force=True)
