"""Analyze PRD Tool

Tool for analyzing Product Requirements Document.
"""

from langchain_core.tools import tool


@tool
def analyze_prd(prd: str) -> str:
    """分析需求规格文档（PRD），并返回分析结果。
    
    Args:
        prd: PRD文档内容
        
    Returns:
        分析结果
    """
    if not prd or not prd.strip():
        return "错误：PRD内容为空"
    
    sections = self._parse_prd_sections(prd)
    
    result = {
        "title": sections.get("title", "未命名"),
        "overview": sections.get("overview", ""),
        "requirements": sections.get("requirements", []),
        "features": sections.get("features", []),
        "constraints": sections.get("constraints", []),
    }
    
    return self._format_analysis_result(result)


def _parse_prd_sections(prd: str) -> dict:
    """Parse PRD into sections
    
    Args:
        prd: PRD content
        
    Returns:
        Parsed sections
    """
    sections = {
        "title": "",
        "overview": "",
        "requirements": [],
        "features": [],
        "constraints": [],
    }
    
    lines = prd.split('\n')
    
    current_section = None
    current_content = []
    
    for line in lines:
        line = line.strip()
        
        if line.startswith('#'):
            if current_section and current_content:
                sections[current_section] = '\n'.join(current_content)
            current_section = line.lower().replace('#', '').replace(' ', '_')
            current_content = []
        elif current_section:
            current_content.append(line)
    
    if current_section and current_content:
        sections[current_section] = '\n'.join(current_content)
    
    return sections


def _format_analysis_result(result: dict) -> str:
    """Format analysis result as readable text
    
    Args:
        result: Analysis result dict
        
    Returns:
        Formatted string
    """
    lines = ["## PRD分析结果\n"]
    
    lines.append(f"### 标题: {result.get('title', '未命名')}\n")
    
    overview = result.get('overview', '')
    if overview:
        lines.append(f"### 概述\n{overview}\n")
    
    features = result.get('features', [])
    if features:
        lines.append("### 功能特性\n")
        for f in features:
            lines.append(f"- {f}")
        lines.append("")
    
    requirements = result.get('requirements', [])
    if requirements:
        lines.append("### 需求\n")
        for r in requirements:
            lines.append(f"- {r}")
        lines.append("")
    
    return '\n'.join(lines)