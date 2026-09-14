"""
可插拔注册表：企业插拔式的核心基础设施。

约定：每个可插拔层（tool / memory / llm_client / planner…）各自持有一个
Registry 实例；实现类通过 ``@registry.register("name")`` 注册；上层只按
配置里的名字调用 ``registry.create(...)`` 创建实例。

效果：新增一种实现（如新的工具、新的记忆后端）只需注册新类，不需要改动
上层编排代码 —— 这就是“可插拔”的落地形态。
"""
from __future__ import annotations

from typing import Callable, Dict, Generic, Optional, Type, TypeVar

from src.common.exceptions import RegistryError

T = TypeVar("T")


class Registry(Generic[T]):
    """
    按名称注册实现类并创建实例的注册表。

    参数:
        name: 注册表名称，仅用于报错信息（如 "tool"）。
        base_type: 期望的实现基类；注册时做 issubclass 校验，可为空跳过。
        default: 未显式指定实现名时使用的默认实现名。
    """

    def __init__(
        self,
        name: str,
        base_type: Optional[Type[T]] = None,
        default: Optional[str] = None,
    ) -> None:
        self.name = name
        self._base_type = base_type
        self._items: Dict[str, Type[T]] = {}
        self._default = default

    # ---------------- 注册 ----------------
    def register(self, name: Optional[str] = None) -> Callable[[Type[T]], Type[T]]:
        """
        类装饰器：
            ``@registry.register()`` 用类名注册，
            ``@registry.register("alias")`` 显式命名。
        """

        def decorator(cls: Type[T]) -> Type[T]:
            key = name or cls.__name__
            self._check_type(cls)
            if key in self._items:
                raise RegistryError(
                    f"registry '{self.name}': 实现名 '{key}' 已注册"
                    f"（{self._items[key].__name__}），禁止重复注册"
                )
            self._items[key] = cls
            return cls

        return decorator

    # ---------------- 查询 ----------------
    def has(self, name: str) -> bool:
        return name in self._items

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

    def get(self, name: Optional[str] = None) -> Type[T]:
        """按名字取实现类；name 为空时用默认实现。"""
        key = name or self._default
        if key is None:
            raise RegistryError(
                f"registry '{self.name}': 未指定实现名且未设置默认实现；可选: {self.names}"
            )
        try:
            return self._items[key]
        except KeyError:
            raise RegistryError(
                f"registry '{self.name}': 实现名 '{key}' 未注册；可选: {self.names}"
            ) from None

    # ---------------- 创建 ----------------
    def create(self, name: Optional[str] = None, **kwargs) -> T:
        """按名字实例化，kwargs 透传给构造函数。"""
        cls = self.get(name)
        try:
            return cls(**kwargs)
        except TypeError as e:
            raise RegistryError(
                f"registry '{self.name}': 创建 '{cls.__name__}' 失败，参数不匹配: {e}"
            ) from e

    # ---------------- 默认实现 ----------------
    def set_default(self, name: str) -> None:
        if name not in self._items:
            raise RegistryError(f"registry '{self.name}': 默认实现 '{name}' 未注册")
        self._default = name

    # ---------------- 内部 ----------------
    def _check_type(self, cls: Type[T]) -> None:
        if self._base_type is None:
            return
        try:
            if not issubclass(cls, self._base_type):  # type: ignore[arg-type]
                raise RegistryError(
                    f"registry '{self.name}': '{cls.__name__}' 不是"
                    f" {self._base_type.__name__} 的子类，禁止注册"
                )
        except TypeError as e:
            raise RegistryError(f"registry '{self.name}': 无法校验类型: {e}") from e
