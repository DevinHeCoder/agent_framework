"""
llm_client 包：统一 LLM 客户端入口（按配置选型）。

用法::

    from src.llm_client import build_llm_client
    llm = build_llm_client(cfg.get("llm"))
    reply = llm.chat([ChatMessage(role="user", content="你好")])

配置选型（config/settings.yaml 的 llm 段）:
    provider: fake | openai_compatible   （默认 fake，无 key 可跑）
    options:  api_key / base_url / model / temperature / timeout
"""
from __future__ import annotations

from typing import Optional

from src.llm_client.base import ChatMessage, LLMClient
from src.llm_client.fake import FakeLLMClient
from src.llm_client.openai_compatible import OpenAICompatibleClient
from src.llm_client.registry import llm_registry

__all__ = [
    "ChatMessage",
    "LLMClient",
    "llm_registry",
    "build_llm_client",
    "FakeLLMClient",
    "OpenAICompatibleClient",
]


def build_llm_client(config: Optional[dict] = None) -> LLMClient:
    """按配置构建 LLM 客户端实例。

    参数:
        config: llm 配置段；缺省按 fake 构建（无 key 可跑全链路）。
                兼容两种结构：{"provider": ..., "options": {...}} 或扁平
                {"provider": ..., "model": ..., "api_key": ...}（settings.yaml 形态）。

    说明: 扁平配置会按目标实现的构造签名自动过滤字段（如 fake 忽略
    base_url/model 等），并剔除空字符串，避免 ${VAR:} 展开的空值误传。
    """
    cfg = dict(config or {})
    provider = cfg.get("provider", "fake")
    options = cfg.get("options") or {}
    if not options:
        # 扁平结构：除 provider/options 外的字段全部作为构造参数
        options = {k: v for k, v in cfg.items() if k not in ("provider", "options")}
    cls = llm_registry.get(provider)
    options = _filter_ctor_kwargs(cls.__init__, options)
    return llm_registry.create(provider, **options)


def _filter_ctor_kwargs(ctor, kwargs: dict) -> dict:
    """按构造函数签名过滤 kwargs：只保留被接受且非空(None/'')的参数。"""
    import inspect

    sig = inspect.signature(ctor)
    accepts_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_kwargs:
        return {k: v for k, v in kwargs.items() if v not in (None, "")}
    accepted = {
        name
        for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {
        k: v for k, v in kwargs.items() if k in accepted and v not in (None, "")
    }
