"""Upload ERP Node — Stage 4

将同步后的 Excel 上传到公司 ERP 系统。
核心逻辑: insurance_agent.tools.erp_uploader.upload_excel_to_erp_with_session_manager()

依赖注入:
    session_manager: SessionManager 实例（管理 JSESSIONID 续期）
"""

import logging
from typing import Any, Optional

from insurance_agent.tools.erp_uploader import upload_excel_to_erp_with_session_manager

logger = logging.getLogger(__name__)


class UploadERPNode:
    """ERP 上传阶段节点

    职责：将 Excel 文件上传到 ERP 系统的 importExcel 接口。
    使用 SessionManager 管理的会话（自动续期 JSESSIONID）。
    """

    def __init__(self, session_manager=None):
        self._session_manager = session_manager

    def __call__(self, state: dict) -> dict:
        """执行 ERP 上传阶段

        state 输入:
            excel_path: Excel 文件路径
            erp_base_url: ERP 基础 URL
            session_manager (通过构造器注入)

        state 输出:
            erp_upload_result: {success, message, file_name, file_size}
            status: "done" / "error"
        """
        logger.info("=== Stage 4: Upload ERP ===")

        excel_path = state.get("excel_path", "")
        erp_base_url = state.get("erp_base_url", "http://47.108.166.14:8081")

        if not excel_path:
            return {
                **state,
                "erp_upload_result": None,
                "status": "error",
                "error": "Excel 文件路径为空",
            }

        if self._session_manager is None:
            logger.error("SessionManager 未注入，跳过 ERP 上传")
            return {
                **state,
                "erp_upload_result": {
                    "success": False,
                    "message": "SessionManager 未注入",
                    "file_name": "",
                    "file_size": 0,
                },
                "status": "error",
                "error": "SessionManager 未注入",
            }

        logger.info("上传 Excel 到 ERP: %s", excel_path)

        try:
            result = upload_excel_to_erp_with_session_manager(
                session_manager=self._session_manager,
                excel_path=excel_path,
                base_url=erp_base_url,
            )

            if result["success"]:
                logger.info("ERP 上传成功: %s", result["message"])
                status = "done"
                error = None
            else:
                logger.error("ERP 上传失败: %s", result["message"])
                status = "error"
                error = result["message"]

            return {
                **state,
                "erp_upload_result": result,
                "status": status,
                "error": error,
            }

        except Exception as e:
            logger.error("ERP 上传异常: %s", e, exc_info=True)
            return {
                **state,
                "erp_upload_result": None,
                "status": "error",
                "error": f"ERP 上传异常: {e}",
            }
