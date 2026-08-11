"""Upload Node — Stage 1

接收上传的 PDF 文件路径，保存到工作目录。
核心逻辑: 文件复制/保存（无外部依赖）
"""

import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)


class UploadNode:
    """上传阶段节点

    职责：将上传的 PDF 文件保存到指定目录。
    如果文件已在目标目录则跳过。
    """

    def __init__(self, upload_dir: str = "C:/insurance-automation/uploads"):
        self._upload_dir = upload_dir

    def __call__(self, state: dict) -> dict:
        """执行上传阶段

        state 输入:
            uploaded_files: PDF 文件路径列表（可能是临时路径）

        state 输出:
            uploaded_files: 保存后的文件路径列表
            status: "extracting"
        """
        logger.info("=== Stage 1: Upload ===")

        uploaded = state.get("uploaded_files", [])
        if not uploaded:
            return {
                **state,
                "status": "error",
                "error": "没有上传任何文件",
            }

        # 确保上传目录存在
        os.makedirs(self._upload_dir, exist_ok=True)

        saved_files = []
        for file_path in uploaded:
            file_path = file_path.replace("\\", "/")
            file_name = os.path.basename(file_path)

            # 如果文件已在目标目录，直接使用
            dest = os.path.join(self._upload_dir, file_name)
            if os.path.abspath(file_path) == os.path.abspath(dest):
                saved_files.append(file_path)
                logger.info("文件已在目标目录: %s", file_name)
                continue

            # 复制到目标目录
            try:
                shutil.copy2(file_path, dest)
                saved_files.append(dest)
                logger.info("已保存: %s → %s", file_name, dest)
            except Exception as e:
                logger.error("保存文件失败 %s: %s", file_name, e)
                # 使用原路径作为兜底
                saved_files.append(file_path)

        return {
            **state,
            "uploaded_files": saved_files,
            "upload_dir": self._upload_dir,
            "status": "extracting",
        }
