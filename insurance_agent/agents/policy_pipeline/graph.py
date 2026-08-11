"""Pipeline Graph — LangGraph 运行图

组装全链路流水线:
    START → upload → extract → sync_excel → upload_erp → END

每个节点是独立工具函数的薄包装，可单独测试。
错误处理: 任何阶段出错 → 直接 END（携带 error 状态）。
"""

import logging

from langgraph.graph import StateGraph, END

from insurance_agent.agents.policy_pipeline.capability import PipelineCapability
from insurance_agent.agents.policy_pipeline.states.pipeline_state import PipelineState

logger = logging.getLogger(__name__)


def build_pipeline_graph(capability: PipelineCapability):
    """构建全链路流水线 LangGraph

    Args:
        capability: PipelineCapability 实例（已注入所有依赖）

    Returns:
        CompiledGraph: 可 invoke 的图

    流程:
        START → upload → extract → sync_excel → upload_erp → END
                    |          |           |
                    ↓ error    ↓ error     ↓ error
                   END        END          END
    """
    nodes = capability.get_nodes()

    graph = StateGraph(PipelineState)

    # 添加节点
    graph.add_node("upload", nodes["upload"])
    graph.add_node("extract", nodes["extract"])
    graph.add_node("sync_excel", nodes["sync_excel"])
    graph.add_node("upload_erp", nodes["upload_erp"])

    # 入口
    graph.set_entry_point("upload")

    # 主流程边 + 错误分支
    def after_upload(state: dict) -> str:
        if state.get("status") == "error":
            return END
        return "extract"

    def after_extract(state: dict) -> str:
        if state.get("status") == "error":
            return END
        return "sync_excel"

    def after_sync_excel(state: dict) -> str:
        if state.get("status") == "error":
            return END
        return "upload_erp"

    graph.add_conditional_edges("upload", after_upload, {
        "extract": "extract",
        END: END,
    })
    graph.add_conditional_edges("extract", after_extract, {
        "sync_excel": "sync_excel",
        END: END,
    })
    graph.add_conditional_edges("sync_excel", after_sync_excel, {
        "upload_erp": "upload_erp",
        END: END,
    })

    # 最后一步
    graph.add_edge("upload_erp", END)

    return graph.compile()


def create_pipeline(
    pdf_parser,
    llm_client=None,
    policy_library=None,
    session_manager=None,
    excel_path: str = "C:/insurance-automation/最新保险数据下载模板.xlsx",
    upload_dir: str = "C:/insurance-automation/uploads",
    erp_base_url: str = "http://47.108.166.14:8081",
):
    """一行创建流水线图

    Returns:
        (capability, compiled_graph)
    """
    capability = PipelineCapability(
        pdf_parser=pdf_parser,
        llm_client=llm_client,
        policy_library=policy_library,
        session_manager=session_manager,
        excel_path=excel_path,
        upload_dir=upload_dir,
        erp_base_url=erp_base_url,
    )
    graph = build_pipeline_graph(capability)
    return capability, graph


__all__ = [
    "build_pipeline_graph",
    "create_pipeline",
]
