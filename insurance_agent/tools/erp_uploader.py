"""ERP 系统上传工具

将 Excel 文件上传到公司 ERP 系统的导入接口。
独立可测，不依赖 Agent 框架。

接口: POST /api/labor/warehousing/importExcel
格式: multipart/form-data, 字段名 file
无需签名头，只需 JSESSIONID cookie

使用方式:
    from insurance_agent.tools.erp_uploader import upload_excel_to_erp
    result = upload_excel_to_erp(
        session=session,  # requests.Session (已登录)
        excel_path="最新保险数据下载模板.xlsx",
        base_url="http://47.108.166.14:8081",
    )
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ERP 接口路径
IMPORT_EXCEL_PATH = "/api/labor/warehousing/importExcel"


def upload_excel_to_erp(
    session: requests.Session,
    excel_path: str,
    base_url: str = "http://47.108.166.14:8081",
) -> dict:
    """上传 Excel 文件到 ERP 系统导入接口

    Args:
        session: 已登录的 requests.Session（含 JSESSIONID cookie）
        excel_path: Excel 文件路径
        base_url: ERP 系统基础 URL

    Returns:
        dict: {
            "success": bool,
            "message": str,        # 服务器返回的消息
            "file_name": str,      # 上传的文件名
            "file_size": int,      # 文件大小(字节)
        }
    """
    if not os.path.exists(excel_path):
        return {
            "success": False,
            "message": f"文件不存在: {excel_path}",
            "file_name": os.path.basename(excel_path),
            "file_size": 0,
        }

    file_name = os.path.basename(excel_path)
    file_size = os.path.getsize(excel_path)
    url = f"{base_url.rstrip('/')}{IMPORT_EXCEL_PATH}"

    logger.info("开始上传 Excel 到 ERP: %s (%d bytes)", file_name, file_size)

    try:
        with open(excel_path, "rb") as f:
            files = {
                "file": (
                    file_name,
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            }
            resp = session.post(url, files=files, timeout=120)

        # 尝试解析 JSON 响应
        try:
            data = resp.json()
            message = data.get("message", "") or data.get("msg", "") or str(data)
            success = data.get("success", False) or "成功" in message
        except (ValueError, requests.exceptions.JSONDecodeError):
            message = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
            success = resp.status_code == 200

        logger.info("ERP 上传结果: success=%s, message=%s", success, message)

        return {
            "success": success,
            "message": message,
            "file_name": file_name,
            "file_size": file_size,
        }

    except requests.exceptions.ConnectionError as e:
        logger.error("ERP 上传连接失败: %s", e)
        return {
            "success": False,
            "message": f"连接失败: {e}",
            "file_name": file_name,
            "file_size": file_size,
        }
    except Exception as e:
        logger.error("ERP 上传异常: %s", e)
        return {
            "success": False,
            "message": f"上传异常: {e}",
            "file_name": file_name,
            "file_size": file_size,
        }


def upload_excel_to_erp_with_session_manager(
    session_manager,
    excel_path: str,
    base_url: str = "http://47.108.166.14:8081",
) -> dict:
    """通过 SessionManager 上传 Excel（自动管理会话）

    Args:
        session_manager: SessionManager 实例
        excel_path: Excel 文件路径
        base_url: ERP 系统基础 URL

    Returns:
        同 upload_excel_to_erp
    """
    session = session_manager.get_session()
    if session is None or not session_manager.is_active():
        logger.warning("会话未激活，尝试重新登录...")
        if not session_manager.login():
            return {
                "success": False,
                "message": "ERP 登录失败，无法上传",
                "file_name": os.path.basename(excel_path),
                "file_size": 0,
            }
        session = session_manager.get_session()

    return upload_excel_to_erp(session, excel_path, base_url)
