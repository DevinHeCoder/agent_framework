"""
自定义异常层级：所有模块异常统一继承 AgentFrameworkError，便于上层统一捕获与兜底。
"""
from typing import Optional


class AgentFrameworkError(Exception):
    """框架所有异常的基类。"""

    def __init__(self, message: str = "", *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


# --- 配置与基础设施（P0）---
class ConfigError(AgentFrameworkError):
    """配置加载 / 解析失败（文件缺失、YAML 语法错误、环境变量未设置等）。"""


class RegistryError(AgentFrameworkError):
    """可插拔注册表操作失败（实现未注册 / 重复注册 / 类型不符 / 参数不匹配）。"""


# --- 工具层（P1）---
class ToolError(AgentFrameworkError):
    """工具注册 / 参数校验 / 执行失败。"""


class ToolNotFoundError(ToolError):
    """请求的工具未注册。"""


class ToolParamError(ToolError):
    """工具参数校验失败（供 Agent 自动修正）。"""


class ToolExecutionError(ToolError):
    """工具执行期异常。"""


# --- 记忆层（P2）---
class MemoryError(AgentFrameworkError):
    """记忆读写失败（连接、序列化、过期等）。"""


# --- LLM 层（P3）---
class LLMError(AgentFrameworkError):
    """LLM 调用失败（网络、限流、鉴权、解析等）。"""


# --- 规划层（P4）---
class PlannerError(AgentFrameworkError):
    """任务规划 / 拆解失败。"""


# --- Agent 层（P4）---
class AgentError(AgentFrameworkError):
    """Agent 主循环失败。"""


class RetryExhaustedError(AgentError):
    """重试 / 参数自动修正达到上限仍失败。"""


# --- 会话层（P5）---
class SessionError(AgentFrameworkError):
    """会话管理失败（会话不存在、持久化失败等）。"""
