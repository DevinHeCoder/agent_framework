"""
Agent 核心抽象基类：TraceEntry + AgentResult + BaseAgent。

Agent 是框架的执行大脑：拿到用户请求后，借助 Planner 拆解任务、通过
ToolRegistry 调用工具、把过程写入 Memory（多轮连续），并套用 RetryPolicy
做异常重试 / 参数自愈 / 失败兜底（需求⑤）。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TraceEntry:
    """单步执行轨迹（供日志 / API 调试 / 前端展示）。"""

    step_id: int
    action: str                    # 工具名或 respond
    args: Dict[str, Any] = field(default_factory=dict)
    observation: str = ""          # 工具结果或失败信息
    status: str = "success"        # success / failed / skipped


@dataclass
class AgentResult:
    """一次 run() 的最终结果。"""

    query: str
    answer: str
    success: bool
    steps_taken: int = 0
    trace: List[TraceEntry] = field(default_factory=list)


class BaseAgent(ABC):
    """智能体统一接口。"""

    @abstractmethod
    def run(self, query: str, session_id: str = "default") -> AgentResult:
        """执行一次用户请求，返回最终回答与执行轨迹。"""
        pass
