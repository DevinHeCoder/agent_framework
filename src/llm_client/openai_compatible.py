"""OpenAI 兼容协议客户端：适配任意兼容端点（OpenAI / DeepSeek / 通义 / 豆包等）。

配置字段（settings.yaml 的 llm.options）:
    api_key / base_url / model / temperature / timeout

设计说明:
- 对 openai 库做惰性导入，未安装时明确报错（不污染其他 provider）；
- 支持注入 client（便于测试复用连接 / 走自定义 transport）。
"""
from typing import Any, List, Optional

from src.common.exceptions import LLMError
from src.llm_client.base import ChatMessage, LLMClient
from src.llm_client.registry import llm_registry

try:  # 惰性依赖：未安装 openai 库时不影响 fake provider 使用
    from openai import OpenAI as _OpenAI
except ImportError:  # pragma: no cover - 取决于运行环境
    _OpenAI = None


@llm_registry.register("openai_compatible")
class OpenAICompatibleClient(LLMClient):
    """基于 openai SDK 的 OpenAI 兼容协议客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        timeout: float = 30.0,
        client: Any = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.temperature = temperature
        if client is not None:
            self._client = client
        else:
            if _OpenAI is None:
                raise LLMError("未安装 openai 库（pip install openai），无法使用 openai_compatible provider")
            self._client = _OpenAI(
                api_key=api_key,
                base_url=base_url or None,
                timeout=timeout,
            )

    def chat(self, messages: List[ChatMessage], **kwargs) -> str:
        payload = [{"role": m.role, "content": m.content} for m in messages]
        params = {
            "model": kwargs.pop("model", self.model),
            "messages": payload,
            "temperature": kwargs.pop("temperature", self.temperature),
            **kwargs,
        }
        try:
            resp = self._client.chat.completions.create(**params)
        except Exception as e:
            raise LLMError(f"LLM 调用失败: {e}") from e
        content = resp.choices[0].message.content
        if content is None:
            raise LLMError("LLM 返回内容为空")
        # 用量统计：OpenAI 兼容响应带 usage 字段（prompt/completion tokens）
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self._report_usage(
                self.model,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        return content

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
