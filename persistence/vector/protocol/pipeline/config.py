from typing import Optional


class PipelineConfig:
    def __init__(
        self,
        enable_async: bool = False,
        enable_transaction: bool = True,
        enable_batch: bool = True,
        batch_size: int = 100,
        validate_dimension: bool = True,
        allow_duplicates: bool = False,
        max_retry: int = 3,
        retry_delay: float = 0.5
    ):
        self.enable_async = enable_async
        self.enable_transaction = enable_transaction
        self.enable_batch = enable_batch
        self.batch_size = batch_size
        self.validate_dimension = validate_dimension
        self.allow_duplicates = allow_duplicates
        self.max_retry = max_retry
        self.retry_delay = retry_delay


class PipelineStats:
    def __init__(self):
        self.total_ingested = 0
        self.total_searched = 0
        self.total_deleted = 0
        self.total_updated = 0
        self.failed_operations = 0
        self.last_operation_time: Optional[float] = None