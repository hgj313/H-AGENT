from abc import ABC, abstractmethod
from typing import Optional

from persistence.vector.implementation.domain.VectorItem import VectorItem


class BaseVectorStorage(ABC):
    def __init__(self, dimension: int):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def add_vectors(self, items: list[VectorItem]) -> int:
        """添加向量到存储，返回实际添加的数量"""
        pass

    @abstractmethod
    def get_vectors(self, ids: list[str]) -> list[VectorItem]:
        pass

    @abstractmethod
    def delete_vectors(self, ids: list[str]) -> int:
        pass

    @abstractmethod
    def update_vectors(self, items: list[VectorItem]) -> int:
        pass
    
    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[VectorItem, float]]:
        pass

    def save(self, path: str) -> None:
        pass

    def load(self, path: str) -> None:
        pass