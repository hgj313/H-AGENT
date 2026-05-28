from abc import ABC, abstractmethod
from typing import Optional, Literal

class BaseSearchEngine(ABC):
    @property
    def distance_metric(self) -> Literal["cosine", "l2", "ip"]:
        return "cosine"
    
    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[str, list[float]]]:
        pass