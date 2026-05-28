"""
向量ID生成器 - 基于内容hash的全局唯一ID
"""
import hashlib
from typing import Optional


class VectorIdGenerator:
    """向量ID生成器
    
    基于内容的SHA256哈希生成唯一ID，确保：
    1. 相同内容产生相同ID（幂等性）
    2. 不同内容产生不同ID（唯一性）
    3. 可通过前缀追溯内容特征
    """
    
    DEFAULT_HASH_LENGTH = 16
    
    @classmethod
    def generate(
        cls,
        content: str,
        prefix: Optional[str] = None,
        hash_length: int = DEFAULT_HASH_LENGTH
    ) -> str:
        """
        生成基于内容的唯一ID
        
        Args:
            content: 向量内容（用于生成hash）
            prefix: 可选前缀（如文档ID、chunk类型等）
            hash_length: hash截取长度，默认16位
            
        Returns:
            str: 生成的唯一ID，格式：prefix_hash前16位
            
        Example:
            >>> VectorIdGenerator.generate("Hello world")
            '7yT2k9X1mQ3nP5wL'
            >>> VectorIdGenerator.generate("Hello world", prefix="doc_001")
            'doc_001_7yT2k9X1mQ3nP5'
            >>> VectorIdGenerator.generate("Hello world", hash_length=8)
            '7yT2k9X1'
        """
        content_hash = cls._hash_content(content)
        short_hash = content_hash[:hash_length]
        
        if prefix:
            return f"{prefix}_{short_hash}"
        return short_hash
    
    @classmethod
    def generate_batch(
        cls,
        items: list[tuple[str, Optional[str]]],
        hash_length: int = DEFAULT_HASH_LENGTH
    ) -> list[str]:
        """
        批量生成ID
        
        Args:
            items: [(content, optional_prefix), ...]
            hash_length: hash截取长度
            
        Returns:
            list[str]: 生成的ID列表
            
        Example:
            >>> items = [("Hello", "doc_1"), ("World", None)]
            >>> VectorIdGenerator.generate_batch(items)
            ['doc_1_a4b5c6d7e8f9g0h1', 'i5j6k7l8m9n0o1p2']
        """
        return [
            cls.generate(content, prefix, hash_length)
            for content, prefix in items
        ]
    
    @staticmethod
    def _hash_content(content: str) -> str:
        """计算内容的SHA256哈希"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    @classmethod
    def is_duplicate(
        cls,
        content: str,
        existing_ids: set[str],
        prefix: Optional[str] = None,
        hash_length: int = DEFAULT_HASH_LENGTH
    ) -> tuple[bool, Optional[str]]:
        """
        检查内容是否会产生重复ID
        
        Args:
            content: 内容
            existing_ids: 已存在的ID集合
            prefix: 可选前缀
            hash_length: hash截取长度
            
        Returns:
            tuple[bool, Optional[str]]: (是否重复, 生成ID)
        """
        generated_id = cls.generate(content, prefix, hash_length)
        is_dup = generated_id in existing_ids
        return is_dup, generated_id