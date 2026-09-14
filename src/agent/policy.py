"""
容错策略（需求⑤）：异常重试 / 参数自动修正 / 失败兜底。

- 工具执行失败（ToolExecutionError）→ 指数退避重试 max_retries 次；
- 参数校验失败（ToolParamError）→ 回喂 LLM 修正参数 param_fix_attempts 次；
- 全程仍失败 → build_fallback() 生成兜底回答，不让流程硬崩。

ReactAgent 依赖本策略：policy 只做纯计算与文案，不直接触碰工具/LLM，
便于单测。
"""
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class RetryPolicy:
    """重试 / 自愈 / 兜底参数集。"""

    max_retries: int = 2            # ToolExecutionError 重试次数
    backoff_base: float = 0.5       # 指数退避基数（秒）：base * 2^attempt
    backoff_cap: float = 8.0        # 退避上限（秒）
    param_fix_attempts: int = 2     # ToolParamError 回喂 LLM 修正次数
    fallback_text: str = "抱歉，我暂时无法完成这个请求。"

    def backoff_seconds(self, attempt: int) -> float:
        """第 attempt 次重试前的等待秒数（指数退避，封顶）。"""
        return min(self.backoff_base * (2 ** attempt), self.backoff_cap)

    def sleep(self, attempt: int) -> None:
        """按指数退避等待（测试可 monkeypatch time.sleep 加速）。"""
        time.sleep(self.backoff_seconds(attempt))

    def build_fallback(self, reason: Optional[Any] = None) -> str:
        """失败兜底文案（附原因，便于上层定位）。"""
        if reason is None:
            return self.fallback_text
        return f"{self.fallback_text}\n（原因：{reason}）"
