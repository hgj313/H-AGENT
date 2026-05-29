from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from agent.graphs.design_review.states.dr_state import DRState
from agent.graphs.design_review.tools.read_file.read_file import read_file_tool


def should_continue(state: DRState) -> Literal["tools", "end"]:
    messages = state["messages"]
    last_msg = messages[-1] if messages else None

    if not last_msg:
        return "end"

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"

    return "end"


def create_design_review_graph(llm):
    graph = StateGraph(DRState)

    llm_with_tools = llm.bind_tools([read_file_tool])
    tool_node = ToolNode([read_file_tool])

    def llm_node(state: DRState) -> dict:
        result = llm_with_tools.invoke(state["messages"])
        return {"messages": [result]}

    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")

    return graph.compile()