from typing import Literal
from langchain_core.messages import AIMessage, ToolMessage
from agent.graphs.design_review.states.dr_state import DRState
from agent.graphs.design_review.tools.read_file.read_file import read_file_tool


def read_file_node(state: DRState) -> dict:
    messages = state["messages"]
    last_msg = messages[-1] if messages else None

    if not isinstance(last_msg, AIMessage):
        return state

    file_path = None
    tool_call_id = None

    for tc in getattr(last_msg, "tool_calls", []):
        if tc.get("name") == "read_file":
            file_path = tc.get("args", {}).get("file_path")
            tool_call_id = tc.get("id")
            break

    if not file_path:
        return state

    result = read_file_tool.invoke({"file_path": file_path})

    return {
        "messages": messages + [ToolMessage(content=result, tool_call_id=tool_call_id)],
        "llm_calls": 0,
    }