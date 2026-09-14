"""
YAML 配置加载：支持文件加载、${ENV} 占位符展开、深合并与环境变量路径覆盖。

典型用法::

    from src.utils.config_loader import load_config
    cfg = load_config()                    # 默认读 config/settings.yaml
    api_key = cfg["llm"]["api_key"]        # 密钥来自环境变量 AGENT_LLM_API_KEY

覆盖机制（优先级从低到高）:
    1. YAML 文件本体
    2. ${ENV_VAR} / ${ENV_VAR:default} 占位符（用于注入密钥、地址等）
    3. 环境变量路径覆盖：AGENT_LLM__MODEL=x 覆盖 cfg["llm"]["model"]
       （前缀 + 顶层键，多级用双下划线 __ 分隔）
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from src.common.constants import DEFAULT_CONFIG_PATH, ENV_PREFIX
from src.common.exceptions import ConfigError

# ${VAR} 或 ${VAR:default}
_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")

PathLike = Union[str, Path]


def load_yaml(path: PathLike) -> Dict[str, Any]:
    """读取单个 YAML 文件为 dict；文件为空时返回空 dict。"""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"配置文件不存在: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"解析 YAML 失败 ({p}): {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"配置文件根节点必须是映射（dict），实际为 {type(data).__name__}: {p}"
        )
    return data


def expand_env(value: Any, _path: str = "$") -> Any:
    """递归展开 ${VAR} / ${VAR:default} 占位符。

    未设置且无默认值时抛 ConfigError，避免静默使用错误配置。
    """
    if isinstance(value, str):
        def _sub(m: "re.Match") -> str:
            var, default = m.group(1), m.group(2)
            env_val = os.environ.get(var)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            raise ConfigError(
                f"配置项 '{_path}' 引用了未设置的环境变量 '{var}'，"
                f"可在配置中用 '${{{var}:默认值}}' 提供默认值"
            )
        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v, f"{_path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, f"{_path}[{i}]") for i, v in enumerate(value)]
    return value


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深合并：override 覆盖 base；嵌套 dict 递归合并，其余类型直接覆盖。不修改入参。"""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def get_path(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """按 'a.b.c' 点路径取值，缺失返回 default。"""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def load_config(
    path: Optional[PathLike] = None,
    *,
    env_prefix: str = ENV_PREFIX,
) -> Dict[str, Any]:
    """加载配置：YAML → ${ENV} 占位符展开 → 环境变量路径覆盖。"""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = load_yaml(p)
    cfg = expand_env(cfg)
    cfg = _apply_env_overrides(cfg, env_prefix)
    return cfg


# ---------------- 内部实现 ----------------
def _apply_env_overrides(cfg: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    """环境变量路径覆盖：AGENT_LLM__MODEL=deepseek-chat 覆盖 cfg['llm']['model']。

    多级路径用双下划线 __ 分隔；值按 YAML 语义尽量转成 bool/int/float。
    """
    result = copy.deepcopy(cfg)
    for env_key, raw in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        parts = [p.lower() for p in env_key[len(prefix):].split("__")]
        node = result
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = _coerce(raw)
    return result


def _coerce(raw: str) -> Any:
    """把环境变量字符串尽量转成 bool/int/float，转不了保持字符串。"""
    low = raw.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(low)
    except ValueError:
        pass
    try:
        return float(low)
    except ValueError:
        return raw
