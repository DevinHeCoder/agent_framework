"""P0 可插拔注册表单测：注册、查询、创建、类型校验、重复注册、默认实现。"""
import pytest

from src.common.exceptions import RegistryError
from src.common.registry import Registry


class Animal:
    def speak(self):  # pragma: no cover
        raise NotImplementedError


class Dog(Animal):
    def speak(self):
        return "woof"


class Cat(Animal):
    def speak(self):
        return "meow"


class NotAnimal:
    pass


def test_register_create_and_default():
    reg = Registry("animal", base_type=Animal, default="Dog")
    reg.register("Dog")(Dog)
    reg.register()(Cat)  # 未命名时用类名
    assert reg.has("Dog") and reg.has("Cat")
    assert set(reg.names) == {"Cat", "Dog"}
    assert isinstance(reg.create(), Dog)        # 走默认
    assert isinstance(reg.create("Cat"), Cat)   # 显式命名


def test_register_wrong_type_raises():
    reg = Registry("animal", base_type=Animal)
    with pytest.raises(RegistryError):
        reg.register("bad")(NotAnimal)


def test_duplicate_register_raises():
    reg = Registry("animal")
    reg.register("a")(Dog)
    with pytest.raises(RegistryError):
        reg.register("a")(Cat)


def test_create_missing_raises():
    reg = Registry("animal")
    with pytest.raises(RegistryError):
        reg.create("nope")
    with pytest.raises(RegistryError):  # 无默认实现
        reg.create()


def test_decorator_syntax():
    reg = Registry("animal", base_type=Animal)

    @reg.register()
    class Bird(Animal):
        def speak(self):
            return "tweet"

    @reg.register("duck")
    class Duck(Animal):
        def speak(self):
            return "quack"

    assert isinstance(reg.create("duck"), Duck)
    assert isinstance(reg.create("Bird"), Bird)
    assert reg.create("duck").speak() == "quack"


def test_create_param_mismatch_raises():
    reg = Registry("animal")

    @reg.register()
    class NeedsArg(Animal):
        def __init__(self, weight: int):
            self.weight = weight

        def speak(self):
            return "x"

    with pytest.raises(RegistryError):
        reg.create("NeedsArg")  # 缺少 weight


def test_set_default():
    reg = Registry("animal")
    reg.register()(Dog)
    reg.register()(Cat)
    reg.set_default("Cat")
    assert isinstance(reg.create(), Cat)


def test_set_default_missing_raises():
    reg = Registry("animal")
    with pytest.raises(RegistryError):
        reg.set_default("nope")
