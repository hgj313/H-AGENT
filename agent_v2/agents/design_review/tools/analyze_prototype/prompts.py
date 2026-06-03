"""Analyze Prototype Prompts"""

ANALYZE_PROTOTYPE_PROMPT = """请分析这张原型图片，提取以下信息并以JSON格式返回：
{
    "page_type": "页面类型",
    "page_name": "页面名称",
    "main_modules": ["主要功能模块列表"],
    "layout_structure": "布局结构描述",
    "interactive_elements": ["交互元素列表"],
    "design_style": "设计风格"
}

要求：
- 回答必须是中文（除了JSON键名）
- 确保JSON格式正确可解析
- 提取所有可见的设计元素"""


ANALYZE_PROTOTYPE_SYSTEM_PROMPT = """你是一个专业的UI/UX设计分析师，擅长分析原型设计图。
你的任务是：
1. 识别页面类型和功能
2. 提取布局和设计元素
3. 生成结构化的分析结果

请始终返回符合JSON格式的分析结果。"""