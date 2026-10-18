"""运行时安全校验与敏感信息脱敏（P0-3 密钥管理）。

两个职责:
1. validate_runtime_security(cfg)：生产环境启动前 fail-fast——
   - 真实 LLM provider 且 API Key 为空/占位 → 抛 ConfigError 拒绝启动（防裸奔）；
   - 生产环境未开启 API 鉴权 → 记录告警日志（不阻断，便于首次部署排障）。
2. redact_secrets(text)：日志/错误信息脱敏，防止 API Key / Bearer Token 落盘。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from src.common.exceptions import ConfigError

logger = logging.getLogger(__name__)

# 视为"未配置"的占位值：settings 默认空串 + .env.example 中的示例值
PLACEHOLDER_API_KEYS = frozenset(
    {"", "sk-你的百炼APIKey", "sk-your-api-key", "sk-xxxx", "your-api-key"}
)

# ---------------- 日志/错误脱敏 ----------------
# 顺序重要：先处理 sk- 与 Bearer，再处理通用 key= 形式
_REDACT_PATTERNS = (
    # sk- 开头的密钥（百炼/OpenAI 兼容格式），保留前缀标记
    (re.compile(r"(?i)\bsk-[a-z0-9._\-]{6,}"), "sk-***"),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{8,}"), "Bearer ***"),
    # api_key=/password=/secret=/token= 等键值对形式（值不落盘）
    (re.compile(r"(?i)(api[_-]?key|password|secret|access[_-]?token|auth[_-]?token)\s*[:=]\s*[^\s,;\"']+"), r"\1=***"),
)


def redact_secrets(text: str) -> str:
    """对文本中的疑似密钥做打码替换；无匹配时原样返回。"""
    if not text:
        return text
    for pattern, repl in _REDACT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


# ---------------- 生产环境校验 ----------------
def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def validate_runtime_security(cfg: Dict[str, Any]) -> None:
    """启动前安全校验（仅 production 生效）。

    Raises:
        ConfigError: production 下 LLM 密钥缺失或为占位值。
    """
    app_cfg = cfg.get("app", {}) or {}
    app_env = str(app_cfg.get("env", "development")).strip().lower()
    if app_env != "production":
        return

    llm_cfg = cfg.get("llm", {}) or {}
    provider = str(llm_cfg.get("provider", "fake")).strip().lower()
    api_key = str(llm_cfg.get("api_key") or "").strip()

    if provider not in ("fake", "mock"):
        if not api_key or api_key in PLACEHOLDER_API_KEYS:
            raise ConfigError(
                "生产环境（AGENT_APP_ENV=production）禁止使用空/占位的 LLM API Key；"
                "请在 .env 中配置 AGENT_LLM_API_KEY 后重新启动"
            )

    auth_cfg = (cfg.get("server", {}) or {}).get("auth", {}) or {}
    if not _to_bool(auth_cfg.get("enabled", False)):
        logger.warning(
            "生产环境建议开启 API 鉴权（AGENT_AUTH_ENABLED=true 并配置 AGENT_AUTH_TOKEN），"
            "防止公网裸奔被盗刷 LLM 额度"
        )
