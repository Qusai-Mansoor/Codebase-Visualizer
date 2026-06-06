from abc import ABC, abstractmethod


class ConcreteABC(ABC):
    @abstractmethod
    def do_thing(self): ...


class ServiceMixin:
    def helper(self):
        pass
