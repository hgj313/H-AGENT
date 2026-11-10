"""飞书多维表格（Bitable）开放 API 客户端

与 `insurance_agent.tools.feishu_webhook_pusher` 的区别：
- webhook pusher 走的是飞书「自动化流程」webhook —— 一次一条、只能新增、无法更新/删除，
  适合「未参保人员提醒」这种小流量场景。
- 本模块走的是 Bitable 开放 API —— 支持批量（≤500 条/次）、更新、删除、查询，
  适合「每日全量打卡数据同步」这种几百条量级的场景。

鉴权流程
--------
1. `POST /open-apis/auth/v3/tenant_access_token/internal` 传 app_id/app_secret
   → 拿到 tenant_access_token（有效期 2 小时），本模块内部缓存并自动续期。
2. 业务接口统一带 `Authorization: Bearer <tenant_access_token>`。

关键约束（来自飞书开放平台文档）
--------------------------------
- 日期/日期时间字段必须传 **13 位毫秒时间戳（int）**，传字符串会报 1254064。
- 数字字段传 int/float，**不接受布尔值**。
- 单选/多选字段必须传**已存在的选项名**，不存在报 1254062 / 1254063。
- batch_create / batch_update 单次最多 500 条记录；限流 10 QPS。
- client_token 需为 uuid 格式，用于幂等（错误格式报 1254037）。

设计约束
--------
- 本模块只负责「鉴权 + HTTP 收发 + 飞书协议细节」，**不含任何打卡业务逻辑**。
- 业务编排（读哪张表、字段怎么映射、如何去重）放在
  `insurance_agent.tools.punch_bitable_sync`。
"""

import logging
import os
import threading
import time
import uuid
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 飞书开放平台根地址
FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"

# 单次批量写入的最大条数（飞书限制 500）
MAX_BATCH_SIZE = 500

# 默认超时（秒）
DEFAULT_TIMEOUT = 15

# tenant_access_token 有效期 2 小时，提前 5 分钟刷新，避免边界失效
_TOKEN_TTL_SECONDS = 2 * 60 * 60
_TOKEN_REFRESH_MARGIN = 5 * 60


class FeishuBitableError(Exception):
    """飞书 Bitable API 业务错误

    Attributes:
        code: 飞书错误码（如 1254041 TableIdNotFound）
        msg: 飞书返回的错误描述
        http_status: HTTP 状态码
    """

    def __init__(self, code, msg: str, http_status: Optional[int] = None):
        self.code = code
        self.msg = msg
        self.http_status = http_status
        super().__init__(f"飞书 API 错误 code={code} msg={msg} http={http_status}")


class FeishuBitableClient:
    """飞书多维表格 API 客户端（线程安全）

    用法::

        client = FeishuBitableClient(
            app_id="cli_xxx", app_secret="xxx",
            app_token="bascnXXX", table_id="tblXXX",
        )
        client.batch_create([{"fields": {"姓名": "张三"}}])
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        app_token: str,
        table_id: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        base_url: str = FEISHU_BASE_URL,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._app_token = app_token
        self._table_id = table_id
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0
        self._lock = threading.Lock()

    # ==================== 鉴权 ====================

    def _fetch_token(self) -> str:
        """向飞书换取 tenant_access_token（不走缓存）"""
        resp = requests.post(
            f"{self._base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self._timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuBitableError(
                data.get("code"), data.get("msg", "获取 token 失败"), resp.status_code
            )
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuBitableError(-1, "响应中没有 tenant_access_token", resp.status_code)
        # expire 是「剩余秒数」
        expire = int(data.get("expire") or _TOKEN_TTL_SECONDS)
        self._token = token
        self._token_expire_at = time.time() + max(expire - _TOKEN_REFRESH_MARGIN, 60)
        logger.info("飞书 tenant_access_token 获取成功，有效期 %ds", expire)
        return token

    def get_token(self) -> str:
        """取 tenant_access_token（带缓存与自动续期，线程安全）"""
        with self._lock:
            if self._token and time.time() < self._token_expire_at:
                return self._token
            return self._fetch_token()

    def invalidate_token(self) -> None:
        """强制下次调用重新取 token（收到 99991663/token 失效时调用）"""
        with self._lock:
            self._token = None
            self._token_expire_at = 0.0

    # ==================== HTTP ====================

    def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        retry_on_auth_error: bool = True,
    ) -> dict:
        """发起一次飞书 API 请求，返回 data 节点

        Raises:
            FeishuBitableError: 飞书返回 code != 0
        """
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            resp = requests.request(
                method, url, json=json_body, params=params, headers=headers, timeout=self._timeout
            )
        except requests.exceptions.RequestException as e:
            raise FeishuBitableError(-1, f"网络异常: {e}") from e

        try:
            data = resp.json()
        except ValueError:
            raise FeishuBitableError(
                -1, f"非 JSON 响应 (HTTP {resp.status_code}): {resp.text[:200]}", resp.status_code
            )

        code = data.get("code")
        if code != 0:
            msg = data.get("msg", "")
            # token 失效 → 强制刷新后重试一次
            if retry_on_auth_error and code in (99991663, 99991668, 99991661):
                logger.warning("飞书 token 失效 (code=%s)，刷新后重试", code)
                self.invalidate_token()
                return self._request(
                    method, path, json_body, params, retry_on_auth_error=False
                )
            raise FeishuBitableError(code, msg, resp.status_code)

        return data.get("data") or {}

    # ==================== 表结构 ====================

    def list_tables(self) -> List[dict]:
        """列出多维表格下的所有数据表

        Returns:
            [{"table_id": "tblXXX", "name": "打卡明细", ...}, ...]
        """
        data = self._request("GET", f"/bitable/v1/apps/{self._app_token}/tables")
        return data.get("items") or []

    def list_fields(self, table_id: str = "") -> List[dict]:
        """列出数据表的字段定义

        Returns:
            [{"field_id": "fldXXX", "field_name": "姓名", "type": 1, ...}, ...]
        """
        tid = table_id or self._table_id
        data = self._request("GET", f"/bitable/v1/apps/{self._app_token}/tables/{tid}/fields")
        return data.get("items") or []

    def resolve_table_id(self, table_name: str = "") -> str:
        """按名称找 table_id；传入名称为空时返回当前配置的 table_id

        Raises:
            ValueError: 找不到同名表
        """
        if not table_name:
            return self._table_id
        for t in self.list_tables():
            if t.get("name") == table_name:
                return t.get("table_id", "")
        raise ValueError(f"多维表格中找不到名为「{table_name}」的数据表")

    # ==================== 记录读写 ====================

    def list_records(
        self,
        table_id: str = "",
        page_size: int = 500,
        filter_json: Optional[dict] = None,
        max_records: int = 0,
    ) -> List[dict]:
        """分页拉取数据表全部记录

        Args:
            filter_json: 飞书过滤表达式（形如
                {"conjunction": "and", "conditions": [{"field_name": "打卡日期", "operator": "is", "value": ["2026-11-10"]}]}）
            max_records: >0 时达到该数量即停止（用于抽样核对）

        Returns:
            [{"record_id": "recXXX", "fields": {...}}, ...]
        """
        tid = table_id or self._table_id
        records: List[dict] = []
        page_token = None

        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            if filter_json:
                params["filter"] = __import__("json").dumps(filter_json, ensure_ascii=False)

            data = self._request("GET", f"/bitable/v1/apps/{self._app_token}/tables/{tid}/records", params=params)
            items = data.get("items") or []
            records.extend(items)

            if max_records and len(records) >= max_records:
                return records[:max_records]
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

        return records

    def batch_create(
        self, records: List[dict], table_id: str = "", client_token: str = ""
    ) -> List[dict]:
        """批量新增记录（自动按 500 条分批）

        Args:
            records: [{"fields": {...}}, ...]
            client_token: uuid 幂等键；留空则自动生成（每次调用新生成）

        Returns:
            新建成功的记录列表 [{"record_id": "recXXX", "fields": {...}}, ...]
        """
        tid = table_id or self._table_id
        created: List[dict] = []

        for chunk in self._chunk(records, MAX_BATCH_SIZE):
            body = {"records": chunk}
            params = {"client_token": client_token or str(uuid.uuid4())}
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self._app_token}/tables/{tid}/records/batch_create",
                json_body=body,
                params=params,
            )
            created.extend(data.get("records") or [])

        return created

    def batch_update(
        self, records: List[dict], table_id: str = "", client_token: str = ""
    ) -> List[dict]:
        """批量更新记录（自动按 500 条分批）

        Args:
            records: [{"record_id": "recXXX", "fields": {...}}, ...]

        Returns:
            更新成功的记录列表
        """
        tid = table_id or self._table_id
        updated: List[dict] = []

        for chunk in self._chunk(records, MAX_BATCH_SIZE):
            body = {"records": chunk}
            params = {"client_token": client_token or str(uuid.uuid4())}
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self._app_token}/tables/{tid}/records/batch_update",
                json_body=body,
                params=params,
            )
            updated.extend(data.get("records") or [])

        return updated

    def batch_delete(self, record_ids: List[str], table_id: str = "") -> int:
        """批量删除记录（自动按 500 条分批），返回删除条数"""
        tid = table_id or self._table_id
        deleted = 0

        for chunk in self._chunk(record_ids, MAX_BATCH_SIZE):
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self._app_token}/tables/{tid}/records/batch_delete",
                json_body={"records": chunk},
            )
            deleted += len(data.get("records") or chunk)

        return deleted

    @staticmethod
    def _chunk(items: List, size: int):
        """把列表切成固定大小的块"""
        for i in range(0, len(items), size):
            yield items[i : i + size]


def load_client_from_config(config: dict) -> FeishuBitableClient:
    """从配置字典构造客户端

    Args:
        config: 需包含 app_id / app_secret / app_token，table_id 可选
    """
    return FeishuBitableClient(
        app_id=config.get("app_id", ""),
        app_secret=config.get("app_secret", ""),
        app_token=config.get("app_token", ""),
        table_id=config.get("table_id", ""),
        timeout=int(config.get("timeout", DEFAULT_TIMEOUT)),
    )
