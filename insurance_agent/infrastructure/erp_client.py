"""ERP 系统 API 客户端

封装公司系统（www.gseerp.com）的数据接口：
- 登录（复用 SessionManager）
- HMAC-SHA256 签名（X-Timestamp / X-Nonce / X-Sign）
- 拉取今日打卡数据（分页）

签名算法（从官网前端 JS 逆向）：
    X-Timestamp = String(Date.now())           # 毫秒时间戳
    X-Nonce     = 8字节随机数的 hex（16字符）
    message     = timestamp + nonce + data_str # GET 请求 data_str 为空
    X-Sign      = HMAC-SHA256(message, SECRET_KEY) 的 hex

SECRET_KEY（官网前端硬编码）:
    c1744f81678da7aa5fca887c18df464ba54dada867bc0b3600ee73958d727377
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ERP 基础地址（生产环境）
ERP_BASE_URL = "https://www.gseerp.com"

# 签名密钥（官网前端硬编码）
SIGN_SECRET_KEY = "c1744f81678da7aa5fca887c18df464ba54dada867bc0b3600ee73958d727377"

# 打卡数据接口
PUNCH_DATA_PATH = "/api/labor/warehousing/findCompleteLaborCalculation/page"

# 项目台账接口（含项目名称与对应项目经理姓名）
PROJECT_ORDERS_PATH = "/api/project/assign/queryOrders"

# 人员信息接口（含项目经理手机/邮箱）
USER_LIST_PATH = "/api/user/queryUserList"


def generate_sign_headers(data_str: str = "") -> dict:
    """生成签名请求头

    Args:
        data_str: 请求体字符串（GET 请求为空；POST JSON 为 JSON.stringify(body)）

    Returns:
        {"X-Timestamp": ..., "X-Nonce": ..., "X-Sign": ...}
    """
    timestamp = str(int(time.time() * 1000))
    nonce = os.urandom(8).hex()
    message = timestamp + nonce + data_str
    sign = hmac.new(
        SIGN_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Sign": sign,
    }


class ERPClient:
    """ERP 数据接口客户端

    复用 SessionManager 维护的 JSESSIONID，自动附加签名头。
    """

    def __init__(self, session_manager, base_url: str = ERP_BASE_URL):
        self._session_manager = session_manager
        self._base_url = base_url.rstrip("/")

    def _get_session(self) -> Optional[requests.Session]:
        """获取已登录会话，未激活则重新登录"""
        session = self._session_manager.get_session()
        if session is None or not self._session_manager.is_active():
            if not self._session_manager.login():
                return None
            session = self._session_manager.get_session()
        return session

    def fetch_punch_data_page(
        self,
        punch_date: str,
        current: int = 1,
        page_size: int = 100,
    ) -> dict:
        """拉取单页打卡数据

        Args:
            punch_date: 打卡日期 YYYY-MM-DD
            current: 页码
            page_size: 每页条数

        Returns:
            {"success", "records": [...], "total": N, "current": ..., "pages": ...}
        """
        session = self._get_session()
        if session is None:
            return {"success": False, "error": "ERP 登录失败"}

        url = f"{self._base_url}{PUNCH_DATA_PATH}"
        headers = generate_sign_headers("")  # GET 请求 body 为空
        params = {
            "punchDate": punch_date,
            "pageSize": page_size,
            "current": current,
        }

        try:
            resp = session.get(url, params=params, headers=headers, timeout=30)
            data = resp.json()
            if not data.get("success"):
                return {
                    "success": False,
                    "error": data.get("message", "未知错误"),
                    "http_status": resp.status_code,
                }
            page_dto = (data.get("data") or {}).get("pageDTO") or {}
            return {
                "success": True,
                "records": page_dto.get("data", []),
                "total": page_dto.get("total", 0),
                "current": page_dto.get("current", current),
                "pages": page_dto.get("pages", 0),
                "statistics": (data.get("data") or {}).get("completeLaborStatistics"),
            }
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "error": f"连接失败: {e}"}
        except Exception as e:
            return {"success": False, "error": f"请求异常: {e}"}

    def fetch_all_punch_data(self, punch_date: str, page_size: int = 500) -> dict:
        """分页拉取全部打卡数据

        Returns:
            {"success", "records": [...全部记录...], "total": N}
        """
        all_records = []
        current = 1
        total = 0

        while True:
            result = self.fetch_punch_data_page(punch_date, current, page_size)
            if not result.get("success"):
                result["records"] = all_records
                return result

            records = result.get("records", [])
            all_records.extend(records)
            total = result.get("total", 0)
            pages = result.get("pages", 0)

            if current >= pages or not records:
                break
            current += 1

        return {
            "success": True,
            "records": all_records,
            "total": total,
        }

    def _fetch_paged(self, path: str, params_base: dict, page_size: int = 20) -> dict:
        """通用翻页拉取（GET + HMAC 签名头，复用已登录 session）

        Returns:
            {"success", "records": [...], "total": N}
        """
        session = self._get_session()
        if session is None:
            return {"success": False, "error": "ERP 登录失败", "records": []}

        all_records = []
        current = 1
        while True:
            headers = generate_sign_headers("")  # GET 请求 body 为空
            params = dict(params_base)
            params["pageSize"] = page_size
            params["current"] = current
            url = f"{self._base_url}{path}"
            try:
                resp = session.get(url, params=params, headers=headers, timeout=30)
                data = resp.json()
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": f"请求异常: {e}", "records": all_records}

            if not data.get("success"):
                return {
                    "success": False,
                    "error": data.get("message", "未知错误"),
                    "http_status": getattr(resp, "status_code", None),
                    "records": all_records,
                }

            # 兼容两种返回结构：data.pageDTO.{data,total,pages} 或 data.data（直接列表）
            page_dto = (data.get("data") or {}).get("pageDTO") or {}
            inner = data.get("data") or {}
            records = page_dto.get("data", []) or inner.get("data", []) or []
            if isinstance(records, dict):
                records = records.get("data", []) or []
            pages = page_dto.get("pages", 0) or inner.get("pages", 0)
            total = page_dto.get("total", 0) or inner.get("total", 0)

            if records:
                all_records.extend(records)
            if current >= (pages or 1) or not records:
                break
            current += 1

        return {"success": True, "records": all_records, "total": len(all_records)}

    def fetch_project_orders(
        self, business_type: str = "LANDSCAPE_ENGINEERING", page_size: int = 500
    ) -> dict:
        """拉取项目台账（含项目名称与对应项目经理姓名）

        返回 {"success", "records": [...原始记录...], "total"}
        """
        return self._fetch_paged(
            PROJECT_ORDERS_PATH,
            {"businessType": business_type},
            page_size=page_size,
        )

    def fetch_user_list(
        self,
        company_id: int = 2,
        department_id: int = 23,
        query_status: str = "all",
        page_size: int = 1000,
    ) -> dict:
        """拉取人员信息（含姓名 / 手机 / 邮箱）

        返回 {"success", "records": [...原始记录...], "total"}
        """
        return self._fetch_paged(
            USER_LIST_PATH,
            {"queryStatus": query_status, "companyId": company_id, "departmentId": department_id},
            page_size=page_size,
        )
