"""Sync Excel Node — Stage 3

将提取结果同步到 Excel 模板（增保新增、减保删除）。
核心逻辑: insurance_agent.tools.excel_sync.sync_excel_with_extraction()
"""

import logging
from typing import Any, Optional

from insurance_agent.tools.excel_sync import sync_excel_with_extraction

logger = logging.getLogger(__name__)


class SyncExcelNode:
    """Excel 同步阶段节点

    职责：将提取的增减保人员同步到 Excel 模板。
    - 增保人员: 证件号不存在则新增，已存在则跳过
    - 减保人员: 按证件号从 Excel 删除
    - 不改变 Excel 原有字段结构
    - 同步前自动备份原文件
    """

    def __init__(self, excel_path: str = "C:/insurance-automation/最新保险数据下载模板.xlsx"):
        self._excel_path = excel_path

    def __call__(self, state: dict) -> dict:
        """执行 Excel 同步阶段

        state 输入:
            extraction_results: 提取结果列表
            excel_path: Excel 模板路径（优先于构造器默认值）

        state 输出:
            sync_stats: {added, removed, skipped, total, backup_path}
            status: "uploading_erp"
        """
        logger.info("=== Stage 3: Sync Excel ===")

        results = state.get("extraction_results", [])
        if not results:
            logger.warning("没有提取结果，跳过 Excel 同步")
            return {
                **state,
                "sync_stats": None,
                "status": "uploading_erp",
            }

        excel_path = state.get("excel_path") or self._excel_path

        logger.info("同步 %d 个提取结果到 Excel: %s", len(results), excel_path)

        try:
            stats = sync_excel_with_extraction(
                excel_path=excel_path,
                extraction_results=results,
            )
            logger.info(
                "Excel 同步完成: 新增 %d, 删除 %d, 跳过 %d, 总计 %d 人",
                stats["added"],
                stats["removed"],
                stats["skipped"],
                stats["total_in_excel"],
            )
            if stats.get("backup_path"):
                logger.info("备份文件: %s", stats["backup_path"])

            return {
                **state,
                "excel_path": excel_path,
                "sync_stats": stats,
                "status": "uploading_erp",
            }

        except Exception as e:
            logger.error("Excel 同步失败: %s", e, exc_info=True)
            return {
                **state,
                "sync_stats": None,
                "status": "error",
                "error": f"Excel 同步失败: {e}",
            }
