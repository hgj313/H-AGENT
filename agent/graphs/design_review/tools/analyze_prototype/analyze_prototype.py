from langchain.tools import tool
from langgraph.prebuilt import tool_node
from llm_model.vision_model.aliyun import VisionModelProvider
from agent.graphs.design_review.tools.analyze_prototype.prompts import ANALYZE_PROTOTYPE_PROMPT

model_provider = VisionModelProvider()
model = model_provider.get_model()

@tool
def analyze_prototype(image_urls: list[str]) -> list[str]:
    """
    分析原型图像。

    args: image_urls: 图片URL列表。

    result: 分析结果列表。
    """
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
                    {"type": "text", "text": "请帮我看看这个图片，把内容以json的形式返回给我(回答必须是中文，除了键以外，值必须是中文描述)"},
                ],
            }
        )
    return model.invoke(messages)
