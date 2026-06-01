from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage

from agent.graphs.design_review.states.dr_state import DRState
from agent.graphs.design_review.tools.read_file.read_file import read_file_tool
from agent.graphs.design_review.nodes.analyze_prototype_node import (
    AnalyzePrototypeNode,
)


def should_continue(state: DRState) -> Literal["tools", "analyze_prototype", "end"]:
    messages = state["messages"]
    last_msg = messages[-1] if messages else None

    if not last_msg:
        return "end"

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"

    has_image, _ = AnalyzePrototypeNode._detect_image_in_message(last_msg)
    if has_image:
        return "analyze_prototype"

    return "end"



def create_design_review_graph(llm):
    graph = StateGraph(DRState)
    tool_node = ToolNode([read_file_tool])
    prototype_node = AnalyzePrototypeNode()

    def llm_node(state: DRState) -> dict:
        result = llm.invoke(state["messages"])
        state["messages"].append(result)
        state["llm_calls"] = state.get("llm_calls", 0) + 1
        return state



    def prototype_analyzer_node(state: DRState) -> dict:
        messages = state["messages"]
        last_msg = messages[-1] if messages else None
        has_image, image_urls = AnalyzePrototypeNode._detect_image_in_message(last_msg)
        
        if not has_image or not image_urls:
            return {"analysis_result": []}
        
        result = prototype_node.analyze(image_urls)
        return result

    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.add_node("analyze_prototype", prototype_analyzer_node)

    graph.set_entry_point("llm")

    graph.add_conditional_edges(
        "llm",
        should_continue,
        {
            "tools": "tools",
            "analyze_prototype": "analyze_prototype",
            "end": END,
        }
    )

    graph.add_edge("tools", "llm")

    graph.add_edge("analyze_prototype", "llm")
    return graph.compile()
