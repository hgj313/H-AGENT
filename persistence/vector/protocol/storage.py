from abc import ABC, abstractmethod
from typing import Optional, Literal

from persistence.vector.implementation.domain.engine import EngineVectorItem


class BaseVectorStorage(ABC):
    def __init__(self, dimension: int):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def count(self) -> int:
        raise NotImplementedError

    @property
    def distance_metric(self) -> Literal["cosine", "l2", "ip"]:
        return "cosine"

    @abstractmethod
    def add_vectors(self, items: list[EngineVectorItem]) -> int:
        """添加向量到存储，返回实际添加的数量"""
        pass

    @abstractmethod
    def get_vectors(self, ids: list[str]) -> list[EngineVectorItem]:
        """根据 IDs 查询向量数据"""
        pass

    @abstractmethod
    def delete_vectors(self, ids: list[str]) -> int:
        pass

    @abstractmethod
    def update_vectors(self, items: list[EngineVectorItem]) -> int:
        pass

    def save(self, path: str) -> None:
        pass

    def load(self, path: str) -> None:
        pass