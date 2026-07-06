"""
web_search 工具 - DuckDuckGo 封装

依赖：duckduckgo-search（pip install duckduckgo-search）
回退：若包未安装，返回明确错误，不抛异常影响主流程。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _do_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """真实调用 DuckDuckGo。失败返回空 list。"""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search 未安装，无法执行 web_search")
        return []
    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(query, max_results=max_results, region="cn-zh")
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("DDG 搜索失败: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in results:
        out.append(
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            }
        )
    return out


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """搜索互联网获取最新信息。输入搜索关键词，返回 JSON 列表 [{title,snippet,url}]

    用法：
        web_search.invoke({"query": "Anthropic Claude 最新模型", "max_results": 5})

    失败时返回 "ERROR: ..." 字符串，调用方应识别。
    """
    if not query or not query.strip():
        return "ERROR: query 不能为空"
    try:
        results = _do_search(query.strip(), int(max_results))
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: 搜索异常 {exc!r}"
    if not results:
        return "ERROR: 无搜索结果（包未安装或被反爬）"
    return json.dumps(results, ensure_ascii=False)
