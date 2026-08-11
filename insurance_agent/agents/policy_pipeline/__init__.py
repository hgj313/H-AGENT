"""Policy Pipeline Agent

全链路流水线: 上传保单 → 提取信息 → 同步Excel → 上传ERP

每个阶段是独立的工具函数，可单独测试:
    - Stage 1 Upload:    nodes/upload_node.py → 文件保存
    - Stage 2 Extract:   nodes/extract_node.py → 调用 invoice_recognition graph
    - Stage 3 SyncExcel: nodes/sync_excel_node.py → tools/excel_sync.py
    - Stage 4 UploadERP: nodes/upload_erp_node.py → tools/erp_uploader.py

组装:
    from insurance_agent.agents.policy_pipeline import create_pipeline, create_pipeline_state

    capability, graph = create_pipeline(
        pdf_parser=PyMuPDFParser(),
        llm_client=llm,
        policy_library=policy_lib,
        session_manager=session_mgr,
        excel_path="最新保险数据下载模板.xlsx",
    )
    result = graph.invoke(create_pipeline_state(uploaded_files=["保单.pdf"]))
"""

from .capability import PipelineCapability
from .graph import build_pipeline_graph, create_pipeline
from .states import PipelineState, create_pipeline_state

__all__ = [
    "PipelineCapability",
    "build_pipeline_graph",
    "create_pipeline",
    "PipelineState",
    "create_pipeline_state",
]
