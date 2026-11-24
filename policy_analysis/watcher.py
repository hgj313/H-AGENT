# -*- coding: utf-8 -*-
"""保单分析监听主程序（轮询）

每 POLL_INTERVAL 秒拉取「保险单」表，发现「保险单号为空」且有 PDF 附件的记录时：
    下载附件 → AI 分析（MiniMax 纯 AI + 保单号正则交叉校验）
             → 回写「保险单」表（保险单号/批单号）+「工人保险清单」表（人员，去重）

关键设计：
1. 「保险单号是否为空」是天然的「是否已处理」标记 —— 已填则跳过，不重复分析。
2. 状态文件记录失败重试次数，连续失败 MAX_ATTEMPTS 次后放弃并告警，防无限重试。
3. 不补历史：已填保险单号的历史记录一律跳过。
"""

import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import (
    PROJECT_ROOT,
    INSURANCE_POLICY_TABLE,
    ATTACHMENT_FIELD,
    POLICY_NO_FIELD,
    POLL_INTERVAL,
    PROCESSED_STATE_PATH,
    LOG_PATH,
    load_feishu_config,
    create_llm_client,
)
from .ai_analyzer import AIAnalyzer
from .writer import PolicyWriter

logger = logging.getLogger("policy_analysis")

MAX_ATTEMPTS = 3


def _setup_logging():
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    # stdout 也打一份（pythonw 下无效但不报错）
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(sh)


def _load_state() -> dict:
    if os.path.exists(PROCESSED_STATE_PATH):
        try:
            with open(PROCESSED_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    try:
        tmp = PROCESSED_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROCESSED_STATE_PATH)
    except Exception as e:
        logger.warning("状态文件写入失败: %s", e)


def _download_attachment(client, url: str, timeout: int = 60) -> bytes:
    """下载附件二进制（url 已带 extra=bitablePerm 参数）"""
    import requests
    headers = {"Authorization": f"Bearer {client.get_token()}"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"附件下载失败 HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.content


class PolicyWatcher:
    def __init__(self):
        feishu_cfg = load_feishu_config()
        from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config
        self._client = load_client_from_config(feishu_cfg)

        llm = create_llm_client()
        from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser
        self._analyzer = AIAnalyzer(llm_client=llm, pdf_parser=PyMuPDFParser())
        self._writer = PolicyWriter(self._client)
        self._state = _load_state()

    def _process_record(self, record: dict) -> None:
        record_id = record["record_id"]
        fields = record.get("fields") or {}
        attachments = fields.get(ATTACHMENT_FIELD) or []
        if not attachments:
            return

        # 只处理第一个附件（当前一条记录对应一个保单文件）
        att = attachments[0]
        file_token = att.get("file_token", "")
        att_name = att.get("name", "unknown.pdf")
        att_url = att.get("url", "")
        fingerprint = f"{record_id}:{file_token}"

        st = self._state.get(fingerprint, {})
        if st.get("attempts", 0) >= MAX_ATTEMPTS:
            logger.warning("记录 %s 已连续失败 %d 次，放弃（需人工处理）", fingerprint, MAX_ATTEMPTS)
            return

        if not att_url:
            logger.warning("附件缺少下载 url: %s", fingerprint)
            return

        logger.info("=== 处理记录 %s 附件 %s ===", fingerprint, att_name)
        try:
            # 1. 下载附件
            pdf_bytes = _download_attachment(self._client, att_url)
            if not pdf_bytes:
                raise RuntimeError("附件内容为空")

            # 2. 落临时文件
            import tempfile
            tmp_dir = tempfile.mkdtemp(prefix="policy_analysis_")
            pdf_path = os.path.join(tmp_dir, att_name if att_name.lower().endswith(".pdf") else att_name + ".pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            try:
                # 3. AI 分析
                result = self._analyzer.analyze(pdf_path, file_name=att_name)
                logger.info(
                    "AI 分析完成(%s)：主保单号=%s 批单号=%s 类型=%s 人员=%d 告警=%s",
                    result["method"],
                    result["main_policy_number"],
                    result["batch_policy_number"],
                    result["policy_type"],
                    len(result["persons"]),
                    result["warnings"],
                )

                if result.get("error"):
                    raise RuntimeError(result["error"])

                # 4. 回写保险单表
                self._writer.write_policy_numbers(
                    record_id,
                    result["main_policy_number"],
                    result["batch_policy_number"],
                )

                # 5. 回写工人保险清单表
                if result["persons"]:
                    self._writer.write_persons(result["persons"], result)

                self._state[fingerprint] = {
                    "done": True,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "policy_number": result["main_policy_number"],
                    "batch_policy_number": result["batch_policy_number"],
                    "persons": len(result["persons"]),
                }
            finally:
                # 清理临时文件
                try:
                    os.remove(pdf_path)
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

        except Exception as e:
            logger.exception("处理失败 %s: %s", fingerprint, e)
            attempts = st.get("attempts", 0) + 1
            self._state[fingerprint] = {
                "failed": True,
                "attempts": attempts,
                "last_error": str(e)[:500],
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

    def run_once(self) -> None:
        """单次轮询"""
        try:
            records = self._client.list_records(INSURANCE_POLICY_TABLE, page_size=500)
        except Exception as e:
            logger.exception("拉取保险单表失败: %s", e)
            return

        pending = 0
        for record in records:
            fields = record.get("fields") or {}
            policy_no = fields.get(POLICY_NO_FIELD)
            if policy_no:
                continue  # 已提取过，跳过
            if not fields.get(ATTACHMENT_FIELD):
                continue  # 无附件
            pending += 1
            self._process_record(record)

        if pending:
            _save_state(self._state)
        logger.info("本轮轮询：总记录 %d，待处理 %d", len(records), pending)

    def run_forever(self) -> None:
        logger.info("保单分析监听启动，轮询间隔 %ds，目标表 %s", POLL_INTERVAL, INSURANCE_POLICY_TABLE)
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception("轮询异常: %s", e)
            time.sleep(POLL_INTERVAL)


def main():
    _setup_logging()
    watcher = PolicyWatcher()
    watcher.run_forever()


if __name__ == "__main__":
    main()
