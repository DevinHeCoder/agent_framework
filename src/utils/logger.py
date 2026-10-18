"""
日志初始化：读取 config/logging.yaml 做 dictConfig；get_logger 为统一入口。

用法::

    from src.utils.logger import get_logger
    logger = get_logger("agent_framework.agent")
    logger.info("...")
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.config
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from src.common.constants import DEFAULT_LOGGING_CONFIG_PATH
from src.common.exceptions import ConfigError
from src.common.security import redact_secrets

PathLike = Union[str, Path]

_configured = False

# 请求级上下文：由 API 中间件设置，日志 filter 注入到每条 record（全链路可串）
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RedactingFormatter(logging.Formatter):
    """日志脱敏格式化器：格式化完成后对全文打码（sk-*、Bearer token 等）。

    在 config/logging.yaml 中通过 ``(): src.utils.logger.RedactingFormatter``
    工厂方式启用；dictConfig 会把 ``format`` / ``datefmt`` 键映射为构造参数。
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return redact_secrets(msg)


class ContextFilter(logging.Filter):
    """把请求上下文（request_id）注入 LogRecord，供 formatter 的 %(request_id)s 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志（一行一条）：time/level/module/msg/request_id 等。

    用于 logs/app.jsonl；仅记录 log 方法显式传入的关键字字段与 record 基础字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # 结构化字段：logger.info("...", extra={...}) 之外的显式 key=value 由
        # caller 通过 record.__dict__ 传入（如 step_id/session_id 等），统一带上
        for key in (
            "session_id",
            "step_id",
            "action",
            "status",
            "duration_ms",
            "retry_count",
            "args_summary",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        text = json.dumps(payload, ensure_ascii=False)
        return redact_secrets(text)


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
