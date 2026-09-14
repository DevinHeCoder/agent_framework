"""
日志初始化：读取 config/logging.yaml 做 dictConfig；get_logger 为统一入口。

用法::

    from src.utils.logger import get_logger
    logger = get_logger("agent_framework.agent")
    logger.info("...")
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Optional, Union

import yaml

from src.common.constants import DEFAULT_LOGGING_CONFIG_PATH
from src.common.exceptions import ConfigError

PathLike = Union[str, Path]

_configured = False


def setup_logging(
    config_path: Optional[PathLike] = None,
    *,
    force: bool = False,
) -> None:
    """按 config/logging.yaml 初始化日志（幂等，force=True 可强制重载）。"""
    global _configured
    if _configured and not force:
        return

    p = Path(config_path) if config_path else DEFAULT_LOGGING_CONFIG_PATH
    if not p.is_file():
        raise ConfigError(f"日志配置文件不存在: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"解析日志配置失败 ({p}): {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"日志配置根节点必须是映射: {p}")

    _ensure_log_dir(raw)
    logging.config.dictConfig(raw)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取命名空间日志器；未初始化时自动初始化一次（配置缺失则退回基础配置）。"""
    global _configured
    if not _configured:
        try:
            setup_logging()
        except ConfigError:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            )
            _configured = True
    return logging.getLogger(name)


# ---------------- 内部实现 ----------------
def _ensure_log_dir(raw: dict) -> None:
    """为 FileHandler / RotatingFileHandler 的 filename 确保父目录存在。"""
    handlers = raw.get("handlers", {})
    for handler in handlers.values():
        filename = handler.get("filename") if isinstance(handler, dict) else None
        if filename:
            Path(filename).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
