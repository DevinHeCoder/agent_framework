"""
规划层抽象基类：Step + Plan + BasePlanner。

LLM 自动任务拆解（需求②）的产物模型：一个用户请求被拆解为有序 Step 列表，
每个 Step 要么调用一个工具（action=工具名 + args），要么直接作答（action=respond）。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class Step:
    """规划中的单步。"""

    step_id: int
    action: str                # 工具名，或 "respond"（直接作答，必须是最后一步）
    args: Dict[str, Any] = field(default_factory=dict)
    thought: str = ""          # 该步骤的规划依据（供 Agent/日志参考）


@dataclass
class Plan:
    """一次任务拆解的完整规划。"""

    query: str
    steps: List[Step]

    def __iter__(self) -> Iterator[Step]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __getitem__(self, i: int) -> Step:
        return self.steps[i]


class BasePlanner(ABC):
    """任务规划器统一接口。"""

    @abstractmethod
    def plan(
        self,
        query: str,
        tools: Optional[List[Any]] = None,
        context: Optional[List[Any]] = None,
    ) -> Plan:
        """把用户请求拆解为有序步骤。

        参数:
            query: 用户请求
            tools: 可用工具的 schema 列表（planner 据此选工具）
            context: 会话历史（多轮连续任务上下文）
        """
        pass
