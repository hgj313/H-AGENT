from abc import ABC, abstractmethod
from typing import Optional

class BaseSearchEngine(ABC):
    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[str, list[float]]]:
        pass