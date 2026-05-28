from abc import ABC, abstractmethod
from typing import Any

from persistence.vector.implementation.domain.ChunkResult import ChunkResult


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkResult]:
        pass

    def _create_metadata(
        self,
        base_metadata: dict[str, Any] | None,
        **kwargs
    ) -> dict[str, Any]:
        meta = dict(base_metadata) if base_metadata else {}
        meta.update(kwargs)
        return meta