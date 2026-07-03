"""Node 1: PolicyParserNode

职责：
- 接收 file_path
- 通过注入的 PDFParser 解析 PDF
- 识别保险公司
- 扫描件时，预转换页面图片为 base64 存入 state（供 OCR 节点使用）
- 存入 state.pdf_document
"""

from dataclasses import asdict
from insurance_agent.infrastructure.parsers import PDFParserProtocol
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


class PolicyParserNode:
    """PDF 解析节点

    DI：通过构造器注入 PDFParserProtocol 实现。
    扫描件时，自动调用 parser.get_page_images() 预转换图片。
    """

    def __init__(self, pdf_parser: PDFParserProtocol):
        self._pdf_parser = pdf_parser

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        file_path = state.get("file_path", "")
        if not file_path:
            return {
                "status": "error",
                "error": "missing_file_path",
                "final_response": '{"error": "未提供 PDF 文件路径"}',
            }

        try:
            pdf_doc = self._pdf_parser.parse(file_path)
        except Exception as e:
            return {
                "status": "error",
                "error": f"pdf_parse_failed: {e}",
                "final_response": f'{{"error": "PDF 解析失败: {e}"}}',
            }

        result = {
            "status": "executing",
            "pdf_document": asdict(pdf_doc),
            "insurance_company": pdf_doc.insurance_company,
            "is_scanned": pdf_doc.is_scanned,
            "tool_results": {
                **state.get("tool_results", {}),
                "policy_parser": {
                    "file_name": pdf_doc.file_name,
                    "total_pages": pdf_doc.total_pages,
                    "is_scanned": pdf_doc.is_scanned,
                    "insurance_company": pdf_doc.insurance_company,
                },
            },
        }

        # 扫描件：预转换页面图片为 base64（供 OCR 节点使用）
        if pdf_doc.is_scanned and hasattr(self._pdf_parser, "get_page_images"):
            try:
                page_images = self._pdf_parser.get_page_images(pdf_doc)
                result["page_images"] = page_images
                result["tool_results"]["policy_parser"]["page_images_count"] = len(page_images)
            except Exception as e:
                result["tool_results"]["policy_parser"]["page_images_error"] = str(e)

        return result


def policy_parser_node(state: InvoiceRecognitionState) -> dict:
    """函数式节点入口（用于 LangGraph.add_node）"""
    # 此函数需要 node 实例；通常在 graph builder 中通过 partial 应用
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
