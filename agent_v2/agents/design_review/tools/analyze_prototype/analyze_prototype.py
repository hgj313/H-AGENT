"""Analyze Prototype Tool

Tool for analyzing prototype images.
Returns design information in structured format.
"""

from langchain_core.tools import tool

try:
    from llm_model.vision_model.aliyun import VisionModelProvider
    model_provider = VisionModelProvider()
    model = model_provider.get_model()
except ImportError:
    model = None


ANALYZE_PROTOTYPE_PROMPT = """请分析这张原型图片，提取以下信息并以JSON格式返回：
1. 页面类型和名称
2. 主要功能模块
3. 布局结构
4. 交互元素
5. 设计风格

回答必须是中文（除了JSON键名）。"""


@tool
def analyze_prototype(image_urls: list[str]) -> list[str]:
    """分析原型图像。
    
    Args:
        image_urls: 图片URL列表
        
    Returns:
        分析结果列表
    """
    if not model:
        return ["错误：视觉模型不可用"]
    
    messages = []
    for image_url in image_urls:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        },
                    },
                    {
                        "type": "text",
                        "text": ANALYZE_PROTOTYPE_PROMPT
                    },
                ],
            }
        )
    
    result = model.invoke(messages)
    
    if hasattr(result, 'content'):
        return [result.content]
    elif isinstance(result, list):
        return [str(r) for r in result]
    else:
        return [str(result)]


class AnalyzePrototypeToolFactory:
    """Factory for creating analyze prototype tool"""
    
    @staticmethod
    def create(custom_model=None):
        """Create analyze prototype tool
        
        Args:
            custom_model: Optional custom model
            
        Returns:
            analyze_prototype tool
        """
        if custom_model:
            global model
            model = custom_model
        
        return analyze_prototype