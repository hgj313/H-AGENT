"""Invoice Recognition State Definition

扩展自 AgentState，添加保险单识别业务字段。
State = 单一真源，所有节点只读写 state。
"""

import operator
from typing import Any, Optional, Annotated, TypedDict
from langchain_core.messages import AnyMessage

from insurance_agent.domain import PDFDocument, ExtractionResult


class InvoiceRecognitionState(TypedDict):
    """保险单识别能力状态

    继承自 AgentState 字段，并扩展：
    - pdf_document: 解析后的 PDF 结构
    - list_pages: 定位到的人员清单页码
    - policy_holder: 投保人/被保险人公司名
    - extraction_result: 最终提取结果
    - policy_holder: 投保人公司名
    - format_hint: 格式提示（table/inline/ocr）
    """
    # --- 继承自 AgentState ---
    messages: Annotated[list[AnyMessage], operator.add]
    user_goal: str
    capability: str
    status: str
    next_action: str
    working_memory: dict[str, Any]
    tool_results: dict[str, Any]
    final_response: str
    error: Optional[str]
    retry_count: int
    metadata: dict[str, Any]

    # --- 业务字段 ---
    file_path: str
    pdf_document: Optional[dict]      # 序列化的 PDFDocument
    insurance_company: str
    is_scanned: bool
    list_pages: list[int]
    policy_holder: str
    format_hint: str                   # table / inline / ocr
    extraction_result: Optional[dict]  # 序列化的 ExtractionResult
    llm_calls: int


def create_invoice_recognition_state(
    user_goal: str = "",
    file_path: str = "",
    thread_id: Optional[str] = None,
) -> dict:
    """工厂函数：创建保险单识别初始 state"""
    return {
        # 基础字段
        "messages": [],
        "user_goal": user_goal,
        "capability": "invoice_recognition",
        "status": "init",
        "next_action": "continue",
        "working_memory": {},
        "tool_results": {},
        "final_response": "",
        "error": None,
        "retry_count": 0,
        "metadata": {"thread_id": thread_id} if thread_id else {},

        # 业务字段
        "file_path": file_path,
        "pdf_document": None,
        "insurance_company": "",
        "is_scanned": False,
        "list_pages": [],
        "policy_holder": "",
        "format_hint": "",
        "extraction_result": None,
        "llm_calls": 0,
    }
