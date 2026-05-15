from langchain.agents import create_agent
from langchain.messages import HumanMessage, AIMessage, SystemMessage

from agent.tools.simple_math import add, subtract, multiply
from llm_model.reasoning_model.minimax import minimax_reasoning_model


config = {"stream_mode": "messages","thread_id": "test-math"}

minimax = minimax_reasoning_model(provider="anthropic")
model = minimax.get_model()
agent = create_agent(model, tools=[add, subtract, multiply])

humanMessages = [HumanMessage(content="请使用工具先计算1+2，再计算3-4，最后计算5*6，结果是多少？")]
chunks = agent.stream({"messages": humanMessages},config=config)
for chunk in chunks:

    # message = chunk.get("model")['messages'][0]
    # content = message.get("content")
    # thinking = message.get("thinking")
    # text = message.get("text")
    # if thinking:
    #     print(f"thinking: {thinking}")
    # if text:
    #     print(f"text: {text}")
        
    print(str(chunk))
    print("\n-----------------\n")

