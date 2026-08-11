"""Pipeline Capability — DI 容器

集中管理流水线各阶段的依赖注入。
遵循 DI 原则：所有外部依赖通过构造器注入，节点不主动创建。
"""

import logging
from typing import Optional

from insurance_agent.agents.policy_pipeline.nodes import (
    UploadNode,
    ExtractNode,
    SyncExcelNode,
    UploadERPNode,
)

logger = logging.getLogger(__name__)


class PipelineCapability:
    """全链路流水线能力容器

    依赖注入:
        pdf_parser: PDF 解析器（必须）
        llm_client: LLM 客户端（可选，扫描件需要）
        policy_library: 保单文件库（可选，批单关联主保单需要）
        session_manager: ERP 会话管理器（可选，无则跳过 ERP 上传）
        excel_path: Excel 模板路径
        upload_dir: 文件上传保存目录
        erp_base_url: ERP 系统基础 URL
    """

    def __init__(
        self,
        pdf_parser,
        llm_client=None,
        policy_library=None,
        session_manager=None,
        excel_path: str = "C:/insurance-automation/最新保险数据下载模板.xlsx",
        upload_dir: str = "C:/insurance-automation/uploads",
        erp_base_url: str = "http://47.108.166.14:8081",
    ):
        self._pdf_parser = pdf_parser
        self._llm_client = llm_client
        self._policy_library = policy_library
        self._session_manager = session_manager
        self._excel_path = excel_path
        self._upload_dir = upload_dir
        self._erp_base_url = erp_base_url

        # 实例化节点
        self._upload_node = UploadNode(upload_dir=upload_dir)
        self._extract_node = ExtractNode(
            pdf_parser=pdf_parser,
            llm_client=llm_client,
            policy_library=policy_library,
        )
        self._sync_excel_node = SyncExcelNode(excel_path=excel_path)
        self._upload_erp_node = UploadERPNode(session_manager=session_manager)

    def get_nodes(self) -> dict:
        """返回节点名称 → 调用对象的映射"""
        return {
            "upload": self._upload_node,
            "extract": self._extract_node,
            "sync_excel": self._sync_excel_node,
            "upload_erp": self._upload_erp_node,
        }

    @property
    def excel_path(self) -> str:
        return self._excel_path

    @property
    def upload_dir(self) -> str:
        return self._upload_dir

    @property
    def erp_base_url(self) -> str:
        return self._erp_base_url
