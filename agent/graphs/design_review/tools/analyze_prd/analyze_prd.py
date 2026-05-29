from langchain_core.tools import BaseTool
from langchain_core.tools import tool

@tool
def analyze_prd(prd: str) -> str:
    """分析需求规格文档（PRD），并返回分析结果"""
    return f"PRD分析结果：{prd}"