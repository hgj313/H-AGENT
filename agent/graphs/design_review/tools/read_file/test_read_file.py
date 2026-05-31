"""文件读取工具测试用例。

覆盖所有支持的文件类型与模型适配场景。
"""
import os
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from typing import Any
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from agent.graphs.design_review.tools.read_file import ReadFileTool
from oss.di import OSSRegistry, OSSConfig
from langchain.messages import HumanMessage




config = OSSConfig(
    region=os.getenv("OSS_REGION"),
    bucket=os.getenv("OSS_BUCKET"),
    access_key_id=os.getenv("OSS_ACCESS_KEY_ID"),
    access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET"),
)

oss_registry = OSSRegistry.get_instance()
oss_registry.register_from_config(config)


def test_read_file():
    model_minimax = MinimaxReasoningModelProvider().get_model()

    graph = create_design_review_graph(model_minimax)
    human_msg = HumanMessage(content="请读取: test_data\测试文档.md")
    result = graph.invoke({"messages": [human_msg]})
    # print(result)
    for msg in result["messages"]:
        print()
        print(type(msg).__name__)
        print("+"*50)
        print(msg.content)
        if hasattr(msg, "tool_calls"):
            print(msg.tool_calls)
            for tool_call in msg.tool_calls:
                print(tool_call.get("name"))
                print(tool_call.get("args"))
                print("-"*50)




if __name__ == '__main__':
    test_read_file()
