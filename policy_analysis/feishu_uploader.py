# -*- coding: utf-8 -*-
"""飞书多维表格附件上传

流程（两步法）：
  1. 上传素材拿 file_token
  2. 写附件字段：{"保单": [{"file_token": "..."}]}

⚠️ 本项目实测（2026-11-26）：
  - `drive/v1/files/upload_all`（官方当前文档路径）→ **99991672 权限不足**
    需开通 drive:drive / drive:file / drive:file:upload
  - `drive/v1/medias/upload_all`（老路径）→ **可用**，返回的 file_token 格式
    与「保险单」表现有附件完全一致（如 JlxBb2XYFopsv5x6rXHcaNMFnZf）
  - `im/v1/files` → 能拿到 file_key（im:resource 权限），但不能直接当附件 token 用
  → 默认走 medias/upload_all，files/upload_all 作为回退（权限开通后自动生效）

⚠️ 官方限制：
  - 上传素材接口**不支持并发调用**，频率上限 5 QPS，超限报 1061045
  - 单文件上限 20MB（更大的要分片上传）
"""

import logging
import os
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

FS_BASE = "https://open.feishu.cn/open-apis"
# 优先用实测可用路径，官方路径作为回退
UPLOAD_PATHS = ("/drive/v1/medias/upload_all", "/drive/v1/files/upload_all")

# 上传点类型：多维表格附件
PARENT_TYPE = "bitable_file"
MIN_INTERVAL = 0.25          # 5 QPS 上限，留一点余量
MAX_RETRY = 4
RETRY_CODES = (1061045, 1061043, 99991400, 1254291)  # 频率/临时错误


class FeishuUploadError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__("上传失败 code=%s msg=%s" % (code, msg))
        self.code = code
        self.msg = msg


class AttachmentUploader:
    """多维表格附件上传器（串行 + 限速 + 退避重试）"""

    def __init__(self, client: Any):
        self._client = client
        self._last_call = 0.0
        self._ok_path = ""      # 已探明可用的上传路径
        # app_token 在 client 里是私有属性 _app_token，这里做兼容取值
        self._app_token = (getattr(client, "app_token", None)
                           or getattr(client, "_app_token", "") or "")

    @property
    def app_token(self) -> str:
        return self._app_token

    def _throttle(self) -> None:
        gap = time.time() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last_call = time.time()

    def upload(self, file_path: str, file_name: Optional[str] = None,
               timeout: int = 300) -> str:
        """上传本地文件，返回 file_token

        依次尝试 UPLOAD_PATHS 中的路径；第一个可用的一直沿用（避免每次都撞权限错误）。
        """
        name = file_name or os.path.basename(file_path)
        size = os.path.getsize(file_path)
        headers = {"Authorization": "Bearer %s" % self._client.get_token()}

        # 已探明的可用路径优先
        paths = [p for p in UPLOAD_PATHS if p == self._ok_path] + \
                [p for p in UPLOAD_PATHS if p != self._ok_path]

        last_err = None
        for path in paths:
            url = FS_BASE + path
            for attempt in range(MAX_RETRY):
                self._throttle()
                try:
                    with open(file_path, "rb") as f:
                        files = {"file": (name, f, "application/pdf")}
                        data = {
                            "file_name": name,
                            "parent_type": PARENT_TYPE,
                            "parent_node": self._app_token,
                            "size": str(size),
                        }
                        resp = requests.post(url, headers=headers, files=files, data=data,
                                             timeout=timeout)
                except requests.exceptions.RequestException as e:
                    last_err = "网络异常: %r" % (e,)
                    time.sleep(2 + attempt * 3)
                    continue

                try:
                    body = resp.json()
                except ValueError:
                    last_err = "非 JSON 响应 HTTP %s: %s" % (resp.status_code, resp.text[:200])
                    time.sleep(2 + attempt * 3)
                    continue

                code = body.get("code")
                if code == 0:
                    token = (body.get("data") or {}).get("file_token")
                    if token:
                        self._ok_path = path
                        logger.info("上传成功[%s] %s → %s (%d bytes)", path, name, token, size)
                        return token
                    last_err = "返回体缺少 file_token: %s" % str(body)[:200]
                else:
                    last_err = "code=%s msg=%s" % (code, body.get("msg", ""))
                    # 权限类错误 → 换下一个路径，不重试
                    if code in (99991672, 99991663) or code not in RETRY_CODES:
                        logger.warning("路径 %s 不可用: %s", path, last_err[:120])
                        break

                logger.warning("上传第 %d 次失败: %s", attempt + 1, last_err)
                time.sleep(2 + attempt * 3)

        raise FeishuUploadError(-1, str(last_err))
