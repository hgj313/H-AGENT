# -*- coding: utf-8 -*-
"""本地保单 PDF → 飞书「保险单」表 批量导入 + AI 分析回写

流程（三阶段，可断点续跑）：
  1. --diff    盘点：本地 policy_library 中【修改月份=目标月】的 PDF，
               按 md5 与「保险单」表已有附件比对，列出待导入清单
  2. --analyze 对清单逐个做 AI 分析（MiniMax），结果缓存到 JSON
               ⚠️ 不写任何飞书数据，可反复重跑
  3. --upload  上传附件 → 新建「保险单」记录（附件+保险单号+批单号+上传日期）
               → 人员信息回写「工人保险清单」

用法::
    python -m policy_analysis.import_local_pdfs --diff --month 2026-11
    python -m policy_analysis.import_local_pdfs --analyze --month 2026-11
    python -m policy_analysis.import_local_pdfs --upload --month 2026-11
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import (
    PROJECT_ROOT,
    INSURANCE_POLICY_TABLE,
    WORKER_INSURANCE_TABLE,
    POLICY_NO_FIELD,
    BATCH_NO_FIELD,
    load_feishu_config,
    create_llm_client,
)

logger = logging.getLogger("import_local_pdfs")

LIB_DIR = os.path.join(PROJECT_ROOT, "policy_library")
CACHE_DIR = os.path.join(PROJECT_ROOT, "_att_cache")
DIFF_FILE = os.path.join(PROJECT_ROOT, "_policy_diff_result.json")
ANALYSIS_FILE = os.path.join(PROJECT_ROOT, "_local_import_analysis.json")
UPLOAD_LOG = os.path.join(PROJECT_ROOT, "_local_import_upload.json")

# ⚠️ 明确排除：非保单 / 测试产物
EXCLUDE_NAMES = {
    "_e2e_scan_4p_hi.pdf",        # e2e 扫描测试产物（4 页纯图片无文本层）
    "test.pdf",                   # 与「替换1人保单·杨正朝周保发0629.pdf」同内容
    "批增1人发票-深圳春羽园林工程有限公司-49.57元(2).pdf",   # 电子发票，非保单
}
EXCLUDE_PATTERNS = ("发票", "_e2e_", "_test_", "~$")

# 「保险单」表字段
F_ATTACHMENT = "保单"
F_UPLOAD_DATE = "上传日期"
F_POLICY_NO = POLICY_NO_FIELD
F_BATCH_NO = BATCH_NO_FIELD


def _setup_logging(verbose: bool = True):
    logger.setLevel(logging.INFO if verbose else logging.WARNING)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(os.path.join(PROJECT_ROOT, "import_local_pdfs.log"),
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(name: str) -> bool:
    if name in EXCLUDE_NAMES:
        return True
    return any(p in name for p in EXCLUDE_PATTERNS)


# ==================== 阶段 1：盘点 ====================

def stage_diff(month: str, client: Any) -> List[dict]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    local = []
    for name in sorted(os.listdir(LIB_DIR)):
        p = os.path.join(LIB_DIR, name)
        if not os.path.isfile(p) or not name.lower().endswith(".pdf"):
            continue
        if is_excluded(name):
            logger.info("排除: %s", name)
            continue
        st = os.stat(p)
        if time.strftime("%Y-%m", time.localtime(st.st_mtime)) != month:
            continue
        local.append({"name": name, "path": p, "size": st.st_size,
                      "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    logger.info("本地 %s 月候选: %d 个", month, len(local))

    # md5 去重
    by_md5: Dict[str, List[dict]] = {}
    for f in local:
        f["md5"] = md5_of(f["path"])
        by_md5.setdefault(f["md5"], []).append(f)
    logger.info("唯一内容: %d（重复 %d）", len(by_md5), len(local) - len(by_md5))

    # 飞书已有附件 md5
    recs = client.list_records(INSURANCE_POLICY_TABLE, page_size=500)
    atts = []
    for r in recs:
        for a in (r.get("fields") or {}).get(F_ATTACHMENT) or []:
            atts.append((r["record_id"], a))
    logger.info("飞书「保险单」表: %d 条记录 / %d 个附件", len(recs), len(atts))

    def dl(item):
        rid, a = item
        tok = a.get("file_token", "")
        cpath = os.path.join(CACHE_DIR, tok + ".bin")
        if not os.path.exists(cpath):
            import requests
            url = a.get("url") or ("https://open.feishu.cn/open-apis/drive/v1/medias/%s/download" % tok)
            headers = {"Authorization": "Bearer %s" % client.get_token()}
            for attempt in range(4):
                try:
                    resp = requests.get(url, headers=headers, timeout=120)
                    if resp.status_code == 200:
                        with open(cpath, "wb") as f:
                            f.write(resp.content)
                        break
                    time.sleep(2 + attempt * 2)
                except Exception:
                    time.sleep(2 + attempt * 2)
            else:
                return None
        try:
            return md5_of(cpath)
        except Exception:
            return None

    remote: Dict[str, List[dict]] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for (rid, a), m in zip(atts, ex.map(dl, atts)):
            if m:
                remote.setdefault(m, []).append({"record_id": rid, "name": a.get("name")})
    logger.info("飞书唯一内容: %d", len(remote))

    missing = []
    for md5, fs in by_md5.items():
        if md5 in remote:
            continue
        f = dict(fs[0])
        f["dup_of"] = [x["name"] for x in fs[1:]]
        missing.append(f)
    missing.sort(key=lambda x: x["name"])

    with open(DIFF_FILE, "w", encoding="utf-8") as f:
        json.dump({"month": month, "missing": missing,
                   "remote_md5_count": len(remote)}, f, ensure_ascii=False, indent=2)
    logger.info("★ 待导入: %d 个 → %s", len(missing), DIFF_FILE)
    for f in missing:
        logger.info("   %-72s %7.1f KB", f["name"][:72], f["size"] / 1024)
    return missing


# ==================== 阶段 2：AI 分析 ====================

def stage_analyze(missing: List[dict], resume: bool = True,
                   force: bool = False) -> Dict[str, Any]:
    """AI 分析阶段

    Args:
        resume: 是否复用已有缓存
        force: 强制重算（忽略缓存里的 ok/skip 状态）—— 规则或 prompt 修完后用
    """
    from .ai_analyzer import AIAnalyzer
    from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser

    cache: Dict[str, Any] = {}
    if resume and os.path.exists(ANALYSIS_FILE):
        try:
            with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            logger.info("载入已有分析缓存: %d 条", len(cache.get("files", [])))
        except Exception:
            cache = {}

    files = cache.setdefault("files", {})
    analyzer = AIAnalyzer(llm_client=create_llm_client(), pdf_parser=PyMuPDFParser())

    ok = err = skip = 0
    for i, f in enumerate(missing, 1):
        key = f["md5"]
        prev = files.get(key)
        if not force and prev and prev.get("status") in ("ok", "skip"):
            ok += 1
            continue
        logger.info("[%d/%d] 分析 %s", i, len(missing), f["name"])
        try:
            result = analyzer.analyze(f["path"], file_name=f["name"])
        except Exception as e:
            logger.exception("分析异常 %s", f["name"])
            files[key] = {"name": f["name"], "path": f["path"], "status": "error",
                          "error": repr(e)}
            err += 1
            continue

        if result.get("error"):
            files[key] = {"name": f["name"], "path": f["path"], "status": "error",
                          "error": result["error"]}
            err += 1
            logger.warning("   ✗ %s", result["error"][:160])
        else:
            main_no = result.get("main_policy_number") or ""
            batch_no = result.get("batch_policy_number") or ""
            if not main_no and not batch_no:
                files[key] = {"name": f["name"], "path": f["path"], "status": "skip",
                              "error": "AI 未提取到保单号/批单号", "result": result}
                skip += 1
                logger.warning("   ✗ 未提取到号（类型=%s）", result.get("policy_type"))
            else:
                files[key] = {"name": f["name"], "path": f["path"], "status": "ok",
                              "persons_count": len(result.get("persons") or []),
                              "result": result}
                ok += 1
                logger.info("   ✓ 主=%s 批=%s 类型=%s 人员=%d 告警=%s",
                            main_no, batch_no, result.get("policy_type"),
                            len(result.get("persons") or []), result.get("warnings"))
        with open(ANALYSIS_FILE, "w", encoding="utf-8") as fo:
            json.dump(cache, fo, ensure_ascii=False, indent=2)

    logger.info("分析完成: 成功 %d，失败 %d，跳过 %d", ok, err, skip)
    return cache


# ==================== 阶段 3：上传 + 回写 ====================

def _clean_empty_primary_rows(client, table_id: str, label: str) -> int:
    """清理「首列为空」的行

    ⚠️ 飞书 Bitable 的隐藏行为：表里一旦存在首列（本表为「姓名」）为空的行，
    后续 batch_create 就会报 `1254045 FieldNameNotFound`（逐条写也失败）。
    这类行在业务上无意义（没有姓名的人员记录），可直接清除。
    """
    try:
        recs = client.list_records(table_id, page_size=500)
    except Exception as e:
        logger.warning("扫描 %s 失败: %s", label, e)
        return 0
    dirty = [r["record_id"] for r in recs
             if not (r.get("fields") or {}).get("姓名")]
    if not dirty:
        return 0
    logger.warning("%s 存在 %d 条首列为空的行（会导致新增报 FieldNameNotFound），清理中",
                   label, len(dirty))
    try:
        client.batch_delete(dirty, table_id=table_id)
    except Exception as e:
        logger.warning("清理 %s 空行失败: %s", label, e)
        return 0
    logger.info("已清理 %s 的 %d 条空行", label, len(dirty))
    return len(dirty)


def _build_attachment_index(client) -> Dict[tuple, tuple]:
    """构建「保险单」表附件幂等索引：(附件名, 字节数) → (record_id, file_token)

    ⚠️ 2026-11-26 实测踩坑：上传日志先写记录后落盘，中途中断会让
    「飞书已建记录、日志里没有」→ 重跑时重复创建同名附件记录。
    这里以「附件名 + 字节数」为幂等键，回表查重自愈。
    """
    index: Dict[tuple, tuple] = {}
    try:
        recs = client.list_records(INSURANCE_POLICY_TABLE, page_size=500)
    except Exception as e:
        logger.warning("扫描「保险单」表失败: %s", e)
        return index
    for r in recs:
        for a in ((r.get("fields") or {}).get(F_ATTACHMENT) or []):
            if not isinstance(a, dict):
                continue
            name = a.get("name")
            size = a.get("size")
            if not (name and size):
                continue
            key = (name, int(size))
            # 同名同尺寸只留 record_id 最小的一条（= 最早创建），
            # 与 dedup_workers / 清理脚本的保留语义保持一致
            prev = index.get(key)
            if prev is None or r["record_id"] < prev[0]:
                index[key] = (r["record_id"], a.get("file_token"))
    return index


def stage_upload(missing: List[dict], cache: Dict[str, Any],
                 force_persons: bool = False) -> Dict[str, Any]:
    from .feishu_uploader import AttachmentUploader
    from .writer import PolicyWriter, _batch_with_fallback

    client = _client()
    uploader = AttachmentUploader(client)
    writer = PolicyWriter(client)
    files = cache.get("files", {})

    # 前置自愈：清掉首列为空的行，否则本批次的 batch_create 会全灭
    _clean_empty_primary_rows(client, WORKER_INSURANCE_TABLE, "工人保险清单")

    # 人员去重索引：整个批次复用一份，避免每个文件都全表扫描（2482 条 × N）
    logger.info("构建工人保险清单去重索引 ...")
    person_index = writer._build_existing_index()
    logger.info("索引键数: %d", len(person_index))

    # 附件幂等索引：(附件名, 字节数) → record_id
    #
    # ⚠️ 为什么需要它（2026-11-26 实测踩坑）：
    #   上传日志 UPLOAD_LOG 是「先写记录、后落盘」的，中途崩溃/被中断时，
    #   飞书里已经建好记录、但日志里没有 → 重跑时 md5 不在 done 集合，
    #   会**再建一条同名附件记录** → 表内出现重复附件。
    #   实测「11.2起保保单-深圳市祥胜建设有限公司」因此被建了 2 次。
    #   → 这里以「附件名 + 字节数」为幂等键，回表查重，命中则复用 record_id。
    logger.info("构建保险单表附件幂等索引 ...")
    att_index = _build_attachment_index(client)
    logger.info("附件索引键数: %d", len(att_index))

    log: Dict[str, Any] = {"uploaded": [], "failed": [], "persons": {}}
    if os.path.exists(UPLOAD_LOG):
        try:
            with open(UPLOAD_LOG, "r", encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            pass
    log.setdefault("uploaded", [])
    log.setdefault("failed", [])
    log.setdefault("persons", {})
    done = {u["md5"] for u in log["uploaded"]}

    for i, f in enumerate(missing, 1):
        md5 = f["md5"]
        rec = files.get(md5)
        if not rec or rec.get("status") != "ok":
            logger.info("[%d/%d] 跳过（分析未通过）%s", i, len(missing), f["name"])
            continue

        result = rec["result"]
        persons = result.get("persons") or []

        # --- 情形 A：附件+记录已建过，只重试人员回写 ---
        if md5 in done:
            prev_p = log["persons"].get(f["name"]) or {}
            # write_persons 内部会吞掉写入异常并返回 0/0，
            # 因此「有人员但统计为 0」同样视为失败，需要重试
            prev_ok = (isinstance(prev_p, dict)
                       and not prev_p.get("error")
                       and (prev_p.get("created", 0) or prev_p.get("updated", 0)))
            if persons and (force_persons or not prev_ok):
                logger.info("[%d/%d] %s人员回写 %s", i, len(missing),
                            "强制" if force_persons else "重试", f["name"])
                try:
                    stat = writer.write_persons(persons, result, index=person_index)
                    log["persons"][f["name"]] = stat
                    logger.info("        人员回写: %s", stat)
                except Exception as e:
                    logger.exception("人员回写失败 %s", f["name"])
                    log["persons"][f["name"]] = {"error": repr(e)}
                with open(UPLOAD_LOG, "w", encoding="utf-8") as fo:
                    json.dump(log, fo, ensure_ascii=False, indent=2)
            else:
                logger.info("[%d/%d] 已上传，跳过 %s", i, len(missing), f["name"])
            continue

        # --- 情形 B：首次上传 ---
        # 0) 附件幂等自愈：日志丢失但表里已有同名同尺寸附件 → 复用已有记录
        local_size = os.path.getsize(f["path"]) if os.path.exists(f["path"]) else 0
        existing = att_index.get((f["name"], local_size))
        token = ""
        if existing:
            record_id, token = existing[0], (existing[1] or "")
            logger.info("[%d/%d] ⚠ 表内已存在同名同尺寸附件，复用记录 %s（不重复创建）",
                        i, len(missing), record_id)
        else:
            # 1) 上传附件
            try:
                token = uploader.upload(f["path"], file_name=f["name"])
            except Exception as e:
                logger.exception("上传失败 %s", f["name"])
                log["failed"].append({"md5": md5, "name": f["name"], "error": repr(e)})
                continue

            # 2) 新建记录（附件 + 号 + 上传日期）
            fields: Dict[str, Any] = {
                F_ATTACHMENT: [{"file_token": token}],
                F_UPLOAD_DATE: int(time.time() * 1000),
            }
            if result.get("main_policy_number"):
                fields[F_POLICY_NO] = result["main_policy_number"]
            if result.get("batch_policy_number"):
                fields[F_BATCH_NO] = result["batch_policy_number"]
            try:
                created = _batch_with_fallback(
                    client.batch_create,
                    [{"fields": fields}],
                    INSURANCE_POLICY_TABLE,
                    "建「保险单」记录")
                record_id = (created[0].get("record_id") or created[0].get("id")) if created else ""
            except Exception as e:
                logger.exception("建记录失败 %s", f["name"])
                log["failed"].append({"md5": md5, "name": f["name"], "error": repr(e)})
                continue
            # 新建的记录加入幂等索引，避免同批次内后续文件撞车
            if local_size:
                att_index[(f["name"], local_size)] = (record_id, token)
        logger.info("[%d/%d] ✓ %s 记录=%s 主=%s 批=%s", i, len(missing),
                    f["name"], record_id, result.get("main_policy_number"),
                    result.get("batch_policy_number"))

        log["uploaded"].append({
            "md5": md5, "name": f["name"], "file_token": token,
            "record_id": record_id,
            "main_policy_number": result.get("main_policy_number"),
            "batch_policy_number": result.get("batch_policy_number"),
            "persons": len(persons), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        with open(UPLOAD_LOG, "w", encoding="utf-8") as fo:
            json.dump(log, fo, ensure_ascii=False, indent=2)

        # 3) 人员回写「工人保险清单」
        if persons:
            try:
                stat = writer.write_persons(persons, result, index=person_index)
                log["persons"][f["name"]] = stat
                logger.info("        人员回写: %s", stat)
            except Exception as e:
                logger.exception("人员回写失败 %s", f["name"])
                log["persons"][f["name"]] = {"error": repr(e)}
            with open(UPLOAD_LOG, "w", encoding="utf-8") as fo:
                json.dump(log, fo, ensure_ascii=False, indent=2)

    logger.info("上传完成: 成功 %d，失败 %d", len(log["uploaded"]), len(log["failed"]))
    pfail = [n for n, v in log["persons"].items() if isinstance(v, dict) and v.get("error")]
    if pfail:
        logger.warning("⚠️ 人员回写失败 %d 个: %s", len(pfail), pfail[:10])
    return log


def _client():
    from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config
    return load_client_from_config(load_feishu_config())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true", help="阶段1 盘点比对")
    ap.add_argument("--analyze", action="store_true", help="阶段2 AI 分析")
    ap.add_argument("--upload", action="store_true", help="阶段3 上传+回写")
    ap.add_argument("--month", default="2026-11", help="目标修改月份 YYYY-MM")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个")
    ap.add_argument("--no-resume", action="store_true", help="忽略已有分析缓存")
    ap.add_argument("--redo", action="store_true", help="强制重算分析（规则/prompt 修完后用）")
    ap.add_argument("--filter", default="", help="只处理文件名包含该子串的文件")
    ap.add_argument("--force-persons", action="store_true",
                    help="强制重写所有人员（修复过 create 缺陷后需要补写）")
    args = ap.parse_args()

    _setup_logging()
    client = _client()

    missing: List[dict] = []
    if args.diff or (not args.analyze and not args.upload):
        missing = stage_diff(args.month, client)
    if args.analyze or args.upload:
        if not missing:
            if os.path.exists(DIFF_FILE):
                with open(DIFF_FILE, "r", encoding="utf-8") as f:
                    missing = json.load(f)["missing"]
                logger.info("从 %s 载入待导入清单: %d 个", DIFF_FILE, len(missing))
            else:
                logger.error("没有待导入清单，请先跑 --diff")
                return 2
        if args.limit:
            missing = missing[:args.limit]
            logger.info("限制处理前 %d 个", len(missing))
        if args.filter:
            before = len(missing)
            missing = [f for f in missing if args.filter in f["name"]]
            logger.info("过滤 %r: %d → %d 个", args.filter, before, len(missing))

    cache: Dict[str, Any] = {}
    if args.analyze or args.upload:
        cache = stage_analyze(missing, resume=not args.no_resume, force=args.redo)
    if args.upload:
        stage_upload(missing, cache, force_persons=args.force_persons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
