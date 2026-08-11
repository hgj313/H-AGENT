"""
通用字符分器
按照段落进行切分，超长段落继续递归切分
"""

import re
import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import Any, Callable,Optional

from persistence.vector.implementation.chunker.chunker_base import BaseChunker
from persistence.vector.implementation.domain.business import BusinessChunkResult

logger = logging.getLogger(__name__)

class GeneralChunker(BaseChunker):
    """
    通用字符切分器（基于 token 计数）

    特点：
    - 按层级分隔符递归切分
    - 使用 token 计数（更准确）
    - 适合各种文本类型
    - 保持语义完整性
    """

    DEFAULT_SEPARATORS = [
        "\n\n",
        "\n",
        "。",
        "！",
        "？",
        "；",
        "，",
        " ",
        "",
    ]

    def __init__(
        self,
        chunk_size: int = 600,
        overlap: int = 90,
        separators: Optional[list[str]] = None,
        length_function: Optional[Callable[[str], int]] = None,
    ):
        """
        初始化切分器

        Args:
            chunk_size: 最大 chunk 大小（tokens）
            overlap: 重叠大小（tokens）
            separators: 分隔符列表（按优先级排序）
            length_function: token 计数函数
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

        if length_function is None:
            length_function = self._token_count

        self.splitter = RecursiveCharacterTextSplitter(
            separators=self.separators,
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=length_function,
            add_start_index=True,
        )

    @staticmethod
    def _token_count(text: str) -> int:
        """估算 token 数量"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    def chunk(
        self,
        text: str,
        metadata: dict[str, Any] | None = None
    ) -> list[BusinessChunkResult]:
        """执行递归切分"""
        if not text or not text.strip():
            return []

        docs = self.splitter.create_documents(
            [text],
            metadatas=[metadata or {}]
        )

        return [
            BusinessChunkResult(
                content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "chunk_type": "text"
                },
                chunk_index=i,
                chunk_type="text"
            )
            for i, doc in enumerate(docs)
        ]