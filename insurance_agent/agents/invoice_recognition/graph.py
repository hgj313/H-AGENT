"""Invoice Recognition Graph

构建保险单识别 Agent 的 LangGraph 流程：
    START → policy_parser → metadata_extractor → personnel_extractor
                → validator → output → END
"""

from langgraph.graph import StateGraph, END

from insurance_agent.agents.invoice_recognition.capability import InvoiceRecognitionCapability
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


def build_invoice_recognition_graph(capability: InvoiceRecognitionCapability):
    """构建保险单识别 LangGraph

    Args:
        capability: InvoiceRecognitionCapability 实例（已注入依赖）

    Returns:
        CompiledGraph: 可 invoke 的图
    """
    nodes = capability.get_nodes()

    graph = StateGraph(InvoiceRecognitionState)

    # 添加节点
    graph.add_node("policy_parser", nodes["policy_parser"])
    graph.add_node("metadata_extractor", nodes["metadata_extractor"])
    graph.add_node("personnel_extractor", nodes["personnel_extractor"])
    graph.add_node("validator", nodes["validator"])
    graph.add_node("output", nodes["output"])

    # 入口
    graph.set_entry_point("policy_parser")

    # 主流程
    graph.add_edge("policy_parser", "metadata_extractor")
    graph.add_edge("metadata_extractor", "personnel_extractor")
    graph.add_edge("personnel_extractor", "validator")

    # validator 条件分支
    def after_validator(state: dict) -> str:
        return "output"

    graph.add_conditional_edges(
        "validator",
        after_validator,
        {"output": "output"},
    )

    graph.add_edge("output", END)

    return graph.compile()


def create_invoice_recognition_graph(pdf_parser):
    """一行创建图"""
    capability = InvoiceRecognitionCapability(pdf_parser=pdf_parser)
    return capability, build_invoice_recognition_graph(capability)


__all__ = [
    "build_invoice_recognition_graph",
    "create_invoice_recognition_graph",
]
