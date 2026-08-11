from abc import ABC, abstractmethod
from typing import Any

from persistence.vector.implementation.domain.business import BusinessChunkResult
from persistence.vector.implementation.domain.engine import EngineVectorItem
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator


class BaseEmbedder(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        pass

    def embed_chunks(self, chunks: list[BusinessChunkResult]) -> list[EngineVectorItem]:
        texts = [c.content for c in chunks]
        vectors = self.embed_documents(texts)
        return [
            EngineVectorItem(
                id=VectorIdGenerator.generate(chunk.content),
                content=chunk.content,
                vector=vector,
                metadata=chunk.metadata,
                chunk_index=chunk.chunk_index,
                chunk_type=chunk.chunk_type
            )
            for chunk, vector in zip(chunks, vectors)
        ]