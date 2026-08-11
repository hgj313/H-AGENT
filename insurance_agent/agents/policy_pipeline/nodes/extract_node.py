"""Extract Node — Stage 2

调用已有的 invoice recognition graph 提取保单信息。
核心逻辑: invoice_recognition graph (5节点: parser → metadata → personnel → validator → output)

依赖注入:
    pdf_parser: PDF 解析器
    llm_client: LLM 客户端（可选，扫描件需要）
    policy_library: 保单文件库（批单关联主保单）
"""

import json
import logging
from typing import Any, Optional

from insurance_agent.agents.invoice_recognition.capability import InvoiceRecognitionCapability
from insurance_agent.agents.invoice_recognition.graph import build_invoice_recognition_graph
from insurance_agent.agents.invoice_recognition.states.inv_state import create_invoice_recognition_state
from insurance_agent.tools import is_main_policy, is_endorsement

logger = logging.getLogger(__name__)


class ExtractNode:
    """提取阶段节点

    职责：对每个 PDF 文件运行保险单识别 graph，收集提取结果。
    文件排序：保单在前，批单在后（保证批单能关联到主保单）。
    """

    def __init__(
        self,
        pdf_parser,
        llm_client=None,
        policy_library=None,
    ):
        self._pdf_parser = pdf_parser
        self._llm_client = llm_client
        self._policy_library = policy_library

    def __call__(self, state: dict) -> dict:
        """执行提取阶段

        state 输入:
            uploaded_files: PDF 文件路径列表

        state 输出:
            extraction_results: 提取结果列表
            extraction_errors: 错误列表
            status: "syncing"
        """
        logger.info("=== Stage 2: Extract ===")

        files = state.get("uploaded_files", [])
        if not files:
            return {
                **state,
                "status": "error",
                "error": "没有文件需要提取",
            }

        # 文件排序：保单在前，批单在后
        main_files = [f for f in files if is_main_policy(f)]
        batch_files = [f for f in files if is_endorsement(f)]
        other_files = [f for f in files if not is_main_policy(f) and not is_endorsement(f)]
        sorted_files = main_files + other_files + batch_files

        logger.info("文件处理顺序: %s", [os.path.basename(f) for f in sorted_files])

        # 创建 capability 和 graph
        capability = InvoiceRecognitionCapability(
            pdf_parser=self._pdf_parser,
            llm_client=self._llm_client,
            policy_library=self._policy_library,
        )
        graph = build_invoice_recognition_graph(capability)

        results = []
        errors = []

        for file_path in sorted_files:
            file_name = os.path.basename(file_path)
            logger.info("正在提取: %s", file_name)

            try:
                initial_state = create_invoice_recognition_state(
                    user_goal=f"提取 {file_name} 中的被保人员清单",
                    file_path=file_path,
                )
                final_state = graph.invoke(initial_state)

                # 解析输出
                final_response = final_state.get("final_response", "")
                if final_response:
                    result = json.loads(final_response)
                    results.append(result)

                    # 注册到保单库（供后续批单关联）
                    if self._policy_library and result.get("policy_number"):
                        self._policy_library.register(result)

                    persons = result.get("insured_persons", [])
                    logger.info(
                        "提取完成: %s → %d 人 (格式: %s)",
                        file_name,
                        len(persons),
                        result.get("format_used", "?"),
                    )
                else:
                    error_msg = f"{file_name}: 无提取结果"
                    errors.append(error_msg)
                    logger.warning(error_msg)

            except Exception as e:
                error_msg = f"{file_name}: {e}"
                errors.append(error_msg)
                logger.error("提取失败: %s", error_msg, exc_info=True)

        return {
            **state,
            "extraction_results": results,
            "extraction_errors": errors,
            "status": "syncing" if results else "error",
            "error": errors[0] if not results and errors else None,
        }


# 在模块顶部导入 os（upload_node 也需要，这里补上 extract_node 的依赖）
import os
