"""Invoice Recognition Capability

封装保险单识别能力的所有组件。
对齐 design_review.DesignReviewCapability 的结构。
"""

from functools import partial

from insurance_agent.infrastructure.parsers import PDFParserProtocol
from insurance_agent.agents.invoice_recognition.states.inv_state import (
    InvoiceRecognitionState,
    create_invoice_recognition_state,
)
from insurance_agent.agents.invoice_recognition.nodes import (
    PolicyParserNode,
    MetadataExtractorNode,
    PersonnelExtractorNode,
    ValidatorNode,
    OutputNode,
)
from insurance_agent.extractors import OCRExtractor


class InvoiceRecognitionCapability:
    """保险单识别能力

    使用方式：
        # 文字层 PDF（不需要 LLM）
        capability = InvoiceRecognitionCapability(pdf_parser=PyMuPDFParser())

        # 扫描件 PDF（需要注入 LLM 客户端）
        llm = ...  # ChatOpenAI 或项目底座 LLM
        capability = InvoiceRecognitionCapability(
            pdf_parser=PyMuPDFParser(),
            llm_client=llm,
        )
        builder = capability.get_graph_builder()
        graph = builder.compile()
        result = graph.invoke(create_invoice_recognition_state(
            file_path="/path/to/policy.pdf"
        ))
    """

    def __init__(self, pdf_parser: PDFParserProtocol, llm_client=None):
        self._pdf_parser = pdf_parser
        self._llm_client = llm_client

        # OCR 提取器（仅当提供了 llm_client 时才创建）
        ocr_extractor = OCRExtractor(llm_client=llm_client) if llm_client else None

        self._policy_parser = PolicyParserNode(pdf_parser=pdf_parser)
        self._metadata_extractor = MetadataExtractorNode()
        self._personnel_extractor = PersonnelExtractorNode(
            ocr_extractor=ocr_extractor,
        )
        self._validator = ValidatorNode()
        self._output = OutputNode()

    @property
    def state_class(self) -> type:
        return InvoiceRecognitionState

    def create_state(
        self,
        user_goal: str = "",
        file_path: str = "",
        thread_id: str = None,
    ) -> dict:
        return create_invoice_recognition_state(
            user_goal=user_goal,
            file_path=file_path,
            thread_id=thread_id,
        )

    def get_nodes(self) -> dict:
        """返回 LangGraph 节点函数（带依赖注入）"""
        return {
            "policy_parser": self._policy_parser,
            "metadata_extractor": self._metadata_extractor,
            "personnel_extractor": self._personnel_extractor,
            "validator": self._validator,
            "output": self._output,
        }
