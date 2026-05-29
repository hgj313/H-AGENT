import asyncio
from langchain.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.aliyun import get_model


async def test_read_file_graph():
    llm = get_model("qwen-plus")

    graph = create_design_review_graph(llm)

    test_file_path = "C:\HGJ-T\H-AGENT\\test_data\测试文档.md"

    messages = [HumanMessage(content=f"请读取文件: {test_file_path}")]

    result = await graph.ainvoke({"messages": messages})

    print("=== 最终结果 ===")
    for msg in result["messages"]:
        print(f"\n[{type(msg).__name__}]")
        print(msg.content[:500] if len(msg.content) > 500 else msg.content)


if __name__ == "__main__":
    asyncio.run(test_read_file_graph())