"""
Markdown文档切分器模块

提供按照标题切分策略，支持：
- 产品设计标准文档（Markdown

"""
import re
import logging

from typing import Any, Callable, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..chunker.chunker_base import BaseChunker
from ..domain import ChunkResult

logger = logging.getLogger(__name__)


class MarkdownChunker(BaseChunker):
    """
    Markdown文档专用切分器

    特点：
    - 基于 Markdown 标题层级切分
    - 保留 header_path 层级结构
    - 表格作为独立 chunk 保留
    """

    DEFAULT_SEPARATORS = [
        "\n## ",    # 二级标题
        "\n# ",     # 一级标题
        "\n\n",     # 段落
        "\n",        # 换行
        "。",        # 句号
        "！",        # 感叹号
        "？",        # 问号
        "；",        # 分号
        "，",        # 逗号
        " ",         # 空格
    ]

    def __init__(
        self,
        chunk_size: int = 600,
        overlap: int = 90,
        min_section_level: int = 1,
        separate_tables: bool = True,
        separators: Optional[list[str]] = None,
        length_function: Optional[Callable[[str], int]] = None,
    ):
        """
        初始化切分器

        Args:
            chunk_size: 目标 chunk 大小（tokens，默认 600 per D-01）
            overlap: chunk 之间的重叠大小（tokens，默认 90 per D-02）
            min_section_level: 最小保留的标题级别（1 = #）
            separate_tables: 是否将表格单独作为 chunk
            separators: 自定义分隔符列表
            length_function: token 计数函数
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_section_level = min_section_level
        self.separate_tables = separate_tables
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
        """
        估算 token 数量

        中文约 1-2 字符/token，英文约 4 字符/token
        这里使用简化估算：中文按 1.5，英文按 4

        Args:
            text: 输入文本

        Returns:
            估算的 token 数量
        """
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    def chunk(
        self,
        text: str,
        metadata: dict[str, Any] | None = None
    ) -> list[ChunkResult]:
        """
        执行切分

        Args:
            text: Markdown 格式的文档内容
            metadata: 基础元数据

        Returns:
            切分结果列表
        """
        if not text or not text.strip():
            return []

        base_meta = metadata or {}

        sections, section_starts, header_paths = self._split_on_headers(text)

        all_chunks = []
        chunk_index = 0

        for idx, section_text in enumerate(sections):
            if not section_text.strip():
                continue

            path = header_paths[idx]
            section_start = section_starts[idx]

            section_meta = {
                "header_path": "/".join(path) if path else "",
                "heading": path[-1] if path else "",
                "heading_level": len(path) if path else 0,
            }

            combined_meta = self._create_metadata(base_meta, **section_meta)

            section_tokens = self._token_count(section_text)

            if section_tokens <= self.chunk_size:
                chunk = ChunkResult(
                    content=section_text.strip(),
                    metadata=combined_meta,
                    chunk_index=chunk_index,
                    chunk_type="text",
                    header_path=path
                )
                chunk.metadata["chunk_start_index"] = section_start
                all_chunks.append(chunk)
                chunk_index += 1
            else:
                section_docs = self.splitter.create_documents(
                    [section_text],
                    metadatas=[combined_meta]
                )

                for section_doc in section_docs:
                    chunk = ChunkResult(
                        content=section_doc.page_content,
                        metadata={
                            **section_doc.metadata,
                            **section_meta,
                            "chunk_start_index": section_start + section_doc.metadata.get("start_index", 0)
                        },
                        chunk_index=chunk_index,
                        chunk_type="text",
                        header_path=path
                    )
                    all_chunks.append(chunk)
                    chunk_index += 1

        if self.separate_tables:
            table_chunks = self._extract_and_create_table_chunks(text, base_meta)
            for i, table_chunk in enumerate(table_chunks):
                table_chunk.chunk_index = chunk_index + i
            all_chunks.extend(table_chunks)

        all_chunks = self._merge_small_chunks(all_chunks)

        for i, chunk in enumerate(all_chunks):
            chunk.chunk_index = i
            chunk.metadata["total_chunks"] = len(all_chunks)

        return all_chunks

    def _merge_small_chunks(self, chunks: list[ChunkResult]) -> list[ChunkResult]:
        """
        合并只有标题的小 chunks
        """
        if not chunks:
            return chunks

        merged = []
        current_chunks = []

        for chunk in chunks:
            if chunk.chunk_type == "table":
                if current_chunks:
                    merged_chunk = self._combine_chunks(current_chunks)
                    if merged_chunk:
                        merged.append(merged_chunk)
                    current_chunks = []
                merged.append(chunk)
                continue

            content_tokens = self._token_count(chunk.content)
            is_small_header_only = content_tokens < 20 and chunk.content.startswith("#")

            if is_small_header_only:
                current_chunks.append(chunk)
            else:
                if current_chunks:
                    merged_chunk = self._combine_chunks(current_chunks)
                    if merged_chunk:
                        merged.append(merged_chunk)
                    current_chunks = []
                current_chunks.append(chunk)

        if current_chunks:
            merged_chunk = self._combine_chunks(current_chunks)
            if merged_chunk:
                merged.append(merged_chunk)

        return merged

    def _combine_chunks(self, chunks: list[ChunkResult]) -> ChunkResult | None:
        """
        将多个 chunks 合并为一个
        """
        if not chunks:
            return None

        combined_content = "\n\n".join(c.content for c in chunks)
        if not combined_content.strip():
            return None

        first_chunk = chunks[0]
        combined_metadata = dict(first_chunk.metadata)

        return ChunkResult(
            content=combined_content,
            metadata=combined_metadata,
            chunk_type="text",
            header_path=first_chunk.header_path
        )

    def _split_on_headers(self, text: str) -> tuple[list[str], list[int], list[list[str]]]:
        """
        按标题切分文本，同时保留标题层级结构

        关键设计：
        - 每个 section 从一个标题开始，到下一个同级或更高级标题结束
        - section 内容包含：标题 + 后续内容
        - header_path 反映当前 section 的标题路径

        Args:
            text: 文本内容

        Returns:
            Tuple of (sections, start_positions, header_paths) where:
            - sections: 每个 section 的文本内容（包含标题）
            - start_positions: 每个 section 在原文本中的字符偏移
            - header_paths: 标题路径列表，如 [["文档标题"], ["文档标题", "第一章"]] 
        """
        sections = []
        start_positions = []
        header_paths = []

        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

        header_stack: list[tuple[int, str]] = []
        current_section_start = 0
        current_section_lines = []
        in_section = False

        for match in header_pattern.finditer(text):
            level = len(match.group(1))
            header_content = match.group(2).strip()
            header_start = match.start()

            if in_section:
                prev_header = header_stack[-1] if header_stack else None
                if prev_header and level <= prev_header[0]:
                    section_text = "\n".join(current_section_lines)
                    if section_text.strip():
                        sections.append(section_text)
                        start_positions.append(current_section_start)
                        header_paths.append([h[1] for h in header_stack])
                    current_section_lines = []

            header_stack = [h for h in header_stack if h[0] < level]
            header_stack.append((level, header_content))

            if not in_section:
                in_section = True

            current_section_start = header_start
            current_section_lines.append(match.group(0))

            next_match = match
            while True:
                next_pos = next_match.end()
                next_match = header_pattern.search(text, next_pos)
                if next_match:
                    section_content = text[current_section_start + len(match.group(0)):next_match.start()]
                    current_section_lines.append(section_content)
                    break
                else:
                    section_content = text[current_section_start + len(match.group(0)):]
                    current_section_lines.append(section_content)
                    break

        if current_section_lines:
            section_text = "\n".join(current_section_lines)
            if section_text.strip():
                sections.append(section_text)
                start_positions.append(current_section_start)
                header_paths.append([h[1] for h in header_stack])

        return sections, start_positions, header_paths

    def _extract_and_create_table_chunks(
        self,
        text: str,
        base_metadata: dict[str, Any]
    ) -> list[ChunkResult]:
        """提取表格并创建独立的 table chunks"""
        table_chunks = []
        tables = self._extract_tables(text)

        for i, table in enumerate(tables):
            table_chunks.append(ChunkResult(
                content=table,
                metadata=self._create_metadata(
                    base_metadata,
                    header_path="",
                    heading=f"表格 {i+1}",
                    heading_level=0,
                    chunk_type="table",
                    table_index=i
                ),
                chunk_type="table",
                header_path=[]
            ))

        return table_chunks

    def _extract_tables(self, text: str) -> list[str]:
        """提取 Markdown 表格"""
        tables = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]
            if re.match(r'^\|.+\|$', line.strip()):
                table_lines = []
                while i < len(lines) and re.match(r'^\|.+\|$', lines[i].strip()):
                    table_lines.append(lines[i])
                    i += 1
                tables.append('\n'.join(table_lines))
                continue
            i += 1

        return tables

