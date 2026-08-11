from abc import ABC, abstractmethod


class PipelineProgressCallback(ABC):
    @abstractmethod
    def on_ingest_start(self, total_chunks: int) -> None:
        pass

    @abstractmethod
    def on_ingest_progress(self, processed: int, total: int) -> None:
        pass

    @abstractmethod
    def on_ingest_complete(self, total_ingested: int) -> None:
        pass

    @abstractmethod
    def on_error(self, error: Exception, operation: str) -> None:
        pass