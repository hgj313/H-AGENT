import asyncio
from langchain.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import minimax_reasoning_model
from llm_model.reasoning_model.aliyun import get_model


llm_qwen = get_model("qwen-plus")


async def test_read_file_graph():
    llm_minimax = minimax_reasoning_model("MiniMax-M2.7").get_model()

    graph = create_design_review_graph(llm_minimax)

    test_file_path = "C:\HGJ-T\H-AGENT\\test_data\测试文档.md"

    messages = [HumanMessage(content=f"请读取文件: {test_file_path}")]

    result = await graph.ainvoke({"messages": messages})

    # print("=== 最终结果 ===")
    # for msg in result["messages"]:
    #     print(f"\n[{type(msg).__name__}]")
    #     print(msg.content[:500] if len(msg.content) > 500 else msg.content)
    print("="*50)
    print("===== 最终结果 ===")
    for message in result['messages']:
        # if hasattr(message, 'tool_calls'):
        #     tool_calls = message.tool_calls[0]
        #     print(tool_calls['name'])
        #     print()
        #     print(tool_calls['args'])
        #     print("="*50)
        #     print("\n")
        # else:
            print(type(message).__name__)
            print("-"*50)
            print(message)
            print("+"*50)
            print("\n")
        # print("="*50)
        # print("\n")
    print(result.get("llm_calls"))

if __name__ == "__main__":
    asyncio.run(test_read_file_graph())