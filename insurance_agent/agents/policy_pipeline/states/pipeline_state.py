"""Policy Pipeline State Definition

全链路流水线状态，串联: 上传保单 → 提取信息 → 同步Excel → 上传ERP
每个阶段是独立的工具函数，节点只做薄包装。
"""

import operator
from typing import Any, Optional, Annotated, TypedDict


class PipelineState(TypedDict):
    """保单处理全链路状态

    阶段流程:
        upload → extract → sync_excel → upload_erp → done

    每个阶段的产出存入对应字段，后续阶段读取使用。
    """

    # --- 基础字段 ---
    status: str           # init / uploading / extracting / syncing / uploading_erp / done / error
    error: Optional[str]  # 错误信息
    stage_results: dict[str, Any]  # 各阶段结果汇总（调试/审计）

    # --- Stage 1: Upload ---
    uploaded_files: list[str]   # 上传的 PDF 文件路径列表
    upload_dir: str             # 文件保存目录

    # --- Stage 2: Extract ---
    extraction_results: list[dict]  # 每个PDF的提取结果 (ExtractionResult.to_dict())
    extraction_errors: list[str]    # 提取过程中的错误（不中断流程）

    # --- Stage 3: Sync Excel ---
    excel_path: str        # Excel 模板路径
    sync_stats: Optional[dict]  # {added, removed, skipped, total, backup_path}

    # --- Stage 4: Upload ERP ---
    erp_upload_result: Optional[dict]  # {success, message, file_name, file_size}
    erp_base_url: str      # ERP 系统基础 URL


def create_pipeline_state(
    uploaded_files: list[str] | None = None,
    upload_dir: str = "",
    excel_path: str = "",
    erp_base_url: str = "http://47.108.166.14:8081",
) -> dict:
    """工厂函数：创建流水线初始 state

    Args:
        uploaded_files: 已上传的 PDF 文件路径列表（如果已上传）
        upload_dir: 文件上传保存目录
        excel_path: Excel 模板路径
        erp_base_url: ERP 系统基础 URL

    Returns:
        初始 state dict
    """
    return {
        "status": "init",
        "error": None,
        "stage_results": {},

        "uploaded_files": uploaded_files or [],
        "upload_dir": upload_dir,

        "extraction_results": [],
        "extraction_errors": [],

        "excel_path": excel_path,
        "sync_stats": None,

        "erp_upload_result": None,
        "erp_base_url": erp_base_url,
    }
