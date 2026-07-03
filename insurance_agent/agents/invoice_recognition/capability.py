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


class InvoiceRecognitionCapability:
    """保险单识别能力

    使用方式：
        capability = InvoiceRecognitionCapability(pdf_parser=PyMuPDFParser())
        builder = capability.get_graph_builder()
        graph = builder.compile()
        result = graph.invoke(create_invoice_recognition_state(
            file_path="/path/to/policy.pdf"
        ))
    """

    def __init__(self, pdf_parser: PDFParserProtocol):
        self._pdf_parser = pdf_parser
        self._policy_parser = PolicyParserNode(pdf_parser=pdf_parser)
        self._metadata_extractor = MetadataExtractorNode()
        self._personnel_extractor = PersonnelExtractorNode()
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
