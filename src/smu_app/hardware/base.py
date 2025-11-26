from abc import ABC, abstractmethod

class SMUBase(ABC):
    @property
    @abstractmethod
    def port(self) -> str:
        pass

    @abstractmethod
    def measure_voltage(self) -> float:
        pass

    @abstractmethod
    def measure_current(self) -> float:
        pass

    def reconnect(self) -> None:
        raise NotImplementedError