from abc import ABC, abstractmethod
from typing import Any

from persistence.vector.protocol.chunker import BaseChunker as ProtocolBaseChunker
from persistence.vector.implementation.domain.business import BusinessChunkResult


class BaseChunker(ProtocolBaseChunker):
    """切分器基类"""

    @abstractmethod
    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[BusinessChunkResult]:
        """
        执行切分

        Args:
            text: 待切分文本
            metadata: 基础元数据

        Returns:
            切分结果列表
        """
        pass

    def _create_metadata(
        self,
        base_metadata: dict[str, Any] | None,
        **kwargs
    ) -> dict[str, Any]:
        """创建元数据"""
        meta = dict(base_metadata) if base_metadata else {}
        meta.update(kwargs)
        return meta