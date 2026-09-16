"""保险单识别 Web 服务

提供前端界面上传 PDF 附件，提取被保人员信息，输出表格文件。
基于现有 insurance_agent 智能体，不修改 Agent 行为，仅做 Web 封装。
"""

import csv
import io
import json
import logging
import os
import sys
import tempfile
import traceback
import ipaddress
from datetime import datetime, timedelta
from typing import Optional, Any
from urllib.parse import quote

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from pydantic import BaseModel

# 确保项目根目录在 path 中（本文件位于 web_app/ 下，上级即项目根）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)

logger = logging.getLogger("insurance_agent.server")

from dotenv import load_dotenv
# 加载 .env：本地开发用 H-AGENT/.env，Docker 部署可挂载到项目根 .env
load_dotenv(os.path.join(_BASE_DIR, "H-AGENT", ".env"))
load_dotenv(os.path.join(_BASE_DIR, ".env"), override=False)

from insurance_agent.infrastructure.parsers import PyMuPDFParser
from insurance_agent.infrastructure import PolicyLibrary
from insurance_agent.infrastructure.session_manager import SessionManager
from insurance_agent.infrastructure.llm.factory import create_minimax_llm_from_env
from insurance_agent.infrastructure import database as db
from insurance_agent.infrastructure.erp_client import ERPClient
from insurance_agent.infrastructure import scheduler as scheduler_mod
from insurance_agent.agents.invoice_recognition import (
    InvoiceRecognitionCapability,
    create_invoice_recognition_state,
    build_invoice_recognition_graph,
)
from insurance_agent.domain import ExtractionResult, InsuredPerson
from insurance_agent.tools import parse_policy_filename, is_main_policy, is_endorsement
from insurance_agent.tools.excel_sync import sync_excel_with_extraction
from insurance_agent.tools.insurance_reminder import (
    run_reminder_check, load_persons_from_json, find_expiring_tomorrow,
    load_config, save_config, get_config_for_response, send_reminder_email,
    run_expiry_check, find_expiring_from_db,
)
from insurance_agent.tools import coverage_check
from insurance_agent.tools.daily_check_service import run_daily_check
from insurance_agent.tools.uninsured_summary import run_uninsured_summary
from insurance_agent.tools.daily_cleanup import run_daily_cleanup
from insurance_agent.tools.feishu_webhook_pusher import (
    init_pusher as init_feishu_pusher,
    get_pusher as get_feishu_pusher,
)
from insurance_agent.tools.realtime_punch_consumer import (
    start_realtime_consumer,
    submit_punch_events,
    get_status as get_realtime_status,
)
from insurance_agent.agents.policy_pipeline import create_pipeline, create_pipeline_state

app = FastAPI(title="保险管理AI助手", version="1.0.0")

# 静态文件
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# 全局状态
_llm_client = None
_policy_library = PolicyLibrary()  # 默认用项目根下的 policy_library 目录
_latest_results: list[dict] = []  # 最近一次提取结果
_graph_cache = None  # 单例 graph，复用避免每次重建
_graph_cache_signature = None  # 上次构建 graph 时的关键文件 mtime 签名（用于代码更新自动重建）

# 关键代码文件列表：变更这些文件应触发 graph 重建
_GRAPH_CODE_FILES = [
    "insurance_agent/agents/invoice_recognition/nodes/policy_parser_node.py",
    "insurance_agent/agents/invoice_recognition/nodes/metadata_extractor_node.py",
    "insurance_agent/agents/invoice_recognition/nodes/personnel_extractor_node.py",
    "insurance_agent/agents/invoice_recognition/nodes/validator_node.py",
    "insurance_agent/agents/invoice_recognition/nodes/output_node.py",
    "insurance_agent/extractors/table_extractor.py",
    "insurance_agent/extractors/inline_extractor.py",
    "insurance_agent/extractors/individual_extractor.py",
    "insurance_agent/extractors/ocr_extractor.py",
]

# 公司系统会话管理器（25分钟自动续期 JSESSIONID）
# 生产环境使用 www.gseerp.com
_session_manager = SessionManager(
    base_url="https://www.gseerp.com",
    username="chenxueqin",
    password="1234",
)


def get_llm():
    """获取 LLM 客户端（延迟初始化）"""
    global _llm_client
    if _llm_client is None:
        try:
            _llm_client = create_minimax_llm_from_env()
        except Exception as e:
            print(f"[WARN] LLM 客户端创建失败: {e}")
    return _llm_client


def _compute_graph_signature() -> tuple:
    """计算 graph 关键代码文件的 mtime 签名

    用于检测代码变更。但**不能**仅靠 signature 自动 rebuild——Python 模块缓存在
    sys.modules 中，需 importlib.reload 显式重载才能生效。完整方案是配合
    `force_reload=True` 调用，或干脆重启服务（见 `/api/agent/info`）。
    """
    sig = {}
    for rel in _GRAPH_CODE_FILES:
        full = os.path.join(_BASE_DIR, rel)
        try:
            sig[rel] = os.path.getmtime(full)
        except OSError:
            sig[rel] = 0.0
    return tuple(sorted(sig.items()))


def _reload_graph_dependencies() -> None:
    """强制 reload 关键代码模块，使其新代码生效（不重启进程）。

    注意：被引用方需一并 reload（如 graph.py 引用了 nodes/*，改了节点文件
    也要 reload graph 模块本身）。下面的顺序按依赖倒序：先 reload 叶子节点。
    """
    import importlib
    mods = [
        "insurance_agent.agents.invoice_recognition.nodes.policy_parser_node",
        "insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node",
        "insurance_agent.agents.invoice_recognition.nodes.personnel_extractor_node",
        "insurance_agent.agents.invoice_recognition.nodes.validator_node",
        "insurance_agent.agents.invoice_recognition.nodes.output_node",
        "insurance_agent.extractors.table_extractor",
        "insurance_agent.extractors.inline_extractor",
        "insurance_agent.extractors.individual_extractor",
        "insurance_agent.extractors.ocr_extractor",
        "insurance_agent.agents.invoice_recognition.capability",
        "insurance_agent.agents.invoice_recognition.graph",
    ]
    for m in mods:
        if m in sys.modules:
            try:
                importlib.reload(sys.modules[m])
            except Exception as e:
                print(f"[WARN] reload {m} 失败: {e}")


def get_invoice_graph(force_rebuild: bool = False):
    """获取单例 invoice recognition graph（避免每次请求重建）

    Args:
        force_rebuild: 强制重建 graph（仅在已 reload 模块后才有意义）
    """
    global _graph_cache, _graph_cache_signature
    if force_rebuild:
        _reload_graph_dependencies()
    if force_rebuild or _graph_cache is None:
        llm = get_llm()
        capability = InvoiceRecognitionCapability(
            pdf_parser=PyMuPDFParser(),
            llm_client=llm,
            policy_library=_policy_library,
        )
        _graph_cache = build_invoice_recognition_graph(capability)
        _graph_cache_signature = _compute_graph_signature()
    return _graph_cache


def _fix_filename(filename: str) -> str:
    """修复中文文件名编码问题

    浏览器/ multipart 上传的中文文件名可能被 Python multipart 库
    以 Latin-1 解码（实际是 GBK 或 UTF-8 字节），导致乱码。
    尝试重新编码还原正确中文。
    """
    if not filename:
        return filename
    # 已经是合法中文则直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in filename):
        return filename
    # 尝试 latin-1 → gbk（Windows 浏览器常见）
    try:
        fixed = filename.encode('latin-1').decode('gbk')
        return fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    # 尝试 latin-1 → utf-8
    try:
        fixed = filename.encode('latin-1').decode('utf-8')
        return fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return filename


def run_agent(pdf_path: str, llm_client=None, policy_library=None) -> dict:
    """运行 Agent 识别单份保单（与 test_agent.py 逻辑一致）

    使用单例 graph，避免每次请求重建 LangGraph。
    """
    graph = get_invoice_graph()
    initial_state = create_invoice_recognition_state(
        user_goal=f"提取 {pdf_path} 中的被保人员清单",
        file_path=pdf_path,
    )
    final_state = graph.invoke(initial_state)
    return final_state


def _process_single_pdf(fpath: str) -> dict:
    """处理单个 PDF 文件（用于并发）"""
    fname = os.path.basename(fpath)
    try:
        final_state = run_agent(fpath)
        result_dict = final_state.get("extraction_result") or {
            "file_name": fname,
            "error": final_state.get("error"),
        }
        result_dict["file_path"] = fpath

        fname_info = parse_policy_filename(fname)
        if not result_dict.get("policy_holder"):
            result_dict["policy_holder"] = fname_info.company

        # 收集 validator_node 的 warnings（用于检测批单主保单缺失等异常）
        warnings = final_state.get("warnings") or []

        # 批单主保单缺失/不匹配检测（2026-09-15 关键防御）：
        # 必须在 persist 之前阻断，否则空日期的人员记录仍会被 upsert 进库
        # （参见 森炜 0072423000 批单错填 6894300 日期事件）
        if fname_info.policy_type == "批单" and not result_dict.get("error"):
            main_missing_warnings = [
                w for w in warnings
                if "未找到对应主保单" in w
                or ("主保单号" in w and "不一致" in w)
            ]
            if main_missing_warnings:
                msg = main_missing_warnings[0]
                return {
                    "file_name": fname,
                    "error": f"批单主保单缺失/不匹配：{msg}",
                    "warnings": warnings,
                    "policy_number": result_dict.get("policy_number", ""),
                    "policy_holder": result_dict.get("policy_holder", ""),
                    "insured_persons": [],
                }

        # 注册到保单文件库
        if not result_dict.get("error"):
            try:
                _policy_library.register(result_dict)
            except Exception:
                pass

        # 保存 PDF 到独立文件空间 + 人员写入数据库
        try:
            _persist_policy_result(result_dict, fpath)
        except Exception:
            pass

        result_dict["warnings"] = warnings
        return result_dict
    except Exception as e:
        return {"file_name": fname, "error": str(e)}


def _persist_policy_result(result_dict: dict, fpath: str):
    """保存保单 PDF 到文件空间，人员写入数据库

    1. PDF 文件复制到 data/policy_pdfs/
    2. 提取的人员写入 insurance_personnel 表
    """
    if result_dict.get("error"):
        return

    # 1. 保存 PDF 到独立文件空间
    try:
        import shutil
        db.ensure_dirs()
        dest = os.path.join(db.PDF_STORAGE_DIR, os.path.basename(fpath))
        if not os.path.exists(dest):
            shutil.copy2(fpath, dest)
    except Exception:
        pass

    # 2. 人员写入数据库（区分增保/减保）
    persons = result_dict.get("insured_persons", [])
    if not persons:
        return

    policy_number = result_dict.get("policy_number", "")
    insurance_company = result_dict.get("insurance_company", "")
    source_file = result_dict.get("file_name", "")
    overall_start = result_dict.get("overall_start_date", "")
    overall_end = result_dict.get("overall_end_date", "")
    # 批单生效日（2026-09-15 新增）：用于减保时同步更新 end_date，避免错填为主保单止期
    endorsement_effective_date = result_dict.get("endorsement_effective_date", "") or ""

    today = datetime.now().strftime("%Y-%m-%d")

    add_rows = []      # 增保人员（新增或更新）
    remove_ids = []    # 减保人员（状态改失效）

    for p in persons:
        mod_type = p.get("modification_type", "增保")
        id_num = (p.get("id_number") or "").strip()

        if mod_type == "减保":
            # 减保：按身份证号标记为失效（end_date 用批单生效日，避免错填为主保单止期）
            if id_num:
                remove_ids.append(id_num)
            continue

        # 增保：新增或更新
        end_date = p.get("end_date", "") or overall_end
        # 状态判断：起止时间未到期 → 正常；已到期 → 失效
        status = "正常"
        if end_date and end_date < today:
            status = "失效"

        add_rows.append({
            "name": p.get("name", ""),
            "id_number": id_num,
            "id_type": p.get("id_type", "身份证"),
            "company": p.get("company", ""),
            "start_date": p.get("start_date", "") or overall_start,
            "end_date": end_date,
            "job_title": p.get("job_title", ""),
            "birth_date": p.get("birth_date", ""),
            "insurance_company": insurance_company,
            "policy_number": policy_number,
            "file_name": source_file,
            "status": status,
        })

    # 增保：新增或更新
    if add_rows:
        db.upsert_insurance_personnel(add_rows)

    # 减保：状态改失效 + 同步 end_date 为批单生效日（2026-09-15 修复 秦克智事件）
    if remove_ids:
        # 优先用 endorsement_effective_date（批单生效日），fallback 到 overall_start（主保单起期）
        # 注意：fallback 到 overall_start 在批单缺失生效日时仍可能错填主保单起期，但至少
        # 不会再出现"end_date > today"的不一致。如果连 overall_start 都没有，则只用 status 兜底。
        deactivate_end_date = endorsement_effective_date or overall_start
        # 2026-09-16 修复徐成强事件：传入 policy_number 限定只减保本批单的记录，
        # 避免跨保单误改（同身份证在不同保单下的记录被无差别失效）。
        if deactivate_end_date:
            db.deactivate_insurance(remove_ids, end_date=deactivate_end_date, policy_number=policy_number)
        else:
            logger.warning(
                f"批单 {source_file} 减保时未提取到批单生效日，"
                f"仅更新 status 而不更新 end_date（可能产生不一致）"
            )
            db.deactivate_insurance(remove_ids, policy_number=policy_number)


def process_files(file_paths: list[str]) -> list[dict]:
    """批量并发处理 PDF 文件

    - 先保单后批单（保证批单能关联到主保单）
    - 保单间并发处理（提升吞吐量）
    - 单个 PDF 失败不影响其他
    """
    # 按保单类型排序
    main_files = [f for f in file_paths if is_main_policy(f)]
    batch_files = [f for f in file_paths if is_endorsement(f)]
    other_files = [f for f in file_paths if not is_main_policy(f) and not is_endorsement(f)]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 保单先并发处理（保单数量通常占多数）
    results: list[dict] = []

    def _run_safe(fpath: str) -> dict:
        try:
            return _process_single_pdf(fpath)
        except Exception as e:
            return {"file_name": os.path.basename(fpath), "error": str(e)}

    # 主保单并发（max_workers=4 避免压垮 LLM）
    if main_files or other_files:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_run_safe, f): f for f in main_files + other_files}
            for fut in as_completed(futures):
                results.append(fut.result())

    # 批单后处理（此时主保单已在保单库中，批单可关联）
    for fpath in batch_files:
        results.append(_run_safe(fpath))

    return results


def results_to_rows(results: list[dict]) -> list[dict]:
    """将提取结果转为扁平化行"""
    all_rows = []
    for r in results:
        if r.get("error"):
            continue
        result = ExtractionResult(
            file_name=r.get("file_name", ""),
            insurance_company=r.get("insurance_company", ""),
            policy_number=r.get("policy_number", ""),
            overall_start_date=r.get("overall_start_date", ""),
            overall_end_date=r.get("overall_end_date", ""),
            insured_persons=[InsuredPerson(**p) for p in r.get("insured_persons", [])],
        )
        all_rows.extend(result.to_csv_rows())
    return all_rows


CSV_FIELDS = [
    "姓名", "证件号码", "证件类型", "出生日期",
    "所属公司", "批改类型",
    "起始时间", "起止时间",
    "岗位名称", "保险公司", "保单号", "来源文件",
]

# 保单人员数据字段映射：Excel 列名 → 数据库字段 key
PERSONNEL_FIELDS = [
    ("姓名", "name"),
    ("证件号码", "id_number"),
    ("证件类型", "id_type"),
    ("出生日期", "birth_date"),
    ("所属公司", "company"),
    ("状态", "status"),
    ("起始时间", "start_date"),
    ("起止时间", "end_date"),
    ("岗位名称", "job_title"),
    ("保险公司", "insurance_company"),
    ("保单号", "policy_number"),
    ("来源文件", "source_file"),
]


# ==================== API ====================

@app.get("/api/health")
async def health():
    return {"status": "ok", "llm_available": _llm_client is not None}


@app.get("/api/agent/info")
async def agent_info():
    """返回 agent 代码版本信息（关键文件 mtime + git commit）

    用于：
    1. 用户/前端核对"代码修复后服务是否已加载新代码"（无需重启，graph 自动重建）
    2. 调试时确认运行中的代码版本
    """
    import os, subprocess, time

    # 关键代码文件 mtime
    files = []
    for rel in _GRAPH_CODE_FILES:
        full = os.path.join(_BASE_DIR, rel)
        try:
            mt = os.path.getmtime(full)
            files.append({
                "path": rel,
                "mtime": mt,
                "mtime_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt)),
            })
        except OSError as e:
            files.append({"path": rel, "error": str(e)})

    # git commit (best-effort)
    git_commit = ""
    try:
        git_commit = subprocess.check_output(
            ["git", "-C", _BASE_DIR, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=2
        ).decode().strip()
    except Exception:
        pass

    # 当前 graph 签名（与磁盘签名对比判断是否需要重建）
    sig = _compute_graph_signature()
    sig_built = _graph_cache_signature
    rebuilt_pending = (sig != sig_built) if sig_built else None

    return {
        "git_commit": git_commit,
        "graph_files": files,
        "graph_signature": list(sig),  # [(path, mtime), ...]
        "graph_signature_built": list(sig_built) if sig_built else None,
        "rebuild_pending": rebuilt_pending,  # True = 下次请求会自动重建
    }


@app.post("/api/agent/reload")
async def agent_reload():
    """手动 reload 关键代码模块并重建 graph（无需重启服务）。

    适用场景：开发者改了 insurance_agent 代码，希望立即生效而不想重启服务。
    仍建议优先重启服务以确保 100% 模块状态一致。
    """
    before_sig = _compute_graph_signature()
    before_built = _graph_cache_signature
    get_invoice_graph(force_rebuild=True)
    after_sig = _compute_graph_signature()
    after_built = _graph_cache_signature

    return {
        "success": True,
        "before_signature": list(before_sig),
        "after_signature": list(after_sig),
        "before_signature_built": list(before_built) if before_built else None,
        "after_signature_built": list(after_built),
    }


@app.get("/api/insurance/inconsistencies")
async def get_insurance_inconsistencies():
    """检测保单人员数据中的不一致记录（2026-09-15 新增）。

    当前实现：status=失效 但 end_date > today 的记录。
    通常由"减保时未同步更新 end_date"或历史脏数据造成。

    返回：
        {
          "today": "2026-09-15",
          "count": 0,
          "records": [...]
        }
    """
    import datetime as _dt
    today = _dt.date.today().isoformat()
    records = db.find_inconsistent_deactivations(today=today)
    return {
        "today": today,
        "count": len(records),
        "records": records,
    }


def _load_upload_token() -> str:
    """从 .env 文件实时读取 UPLOAD_API_TOKEN（热加载，免重启）。

    依次检查项目根 .env 与 H-AGENT/.env，命中即返回，避免依赖进程启动时的
    os.environ 快照导致改完 .env 还要重启服务。
    """
    candidates = [
        os.path.join(_BASE_DIR, ".env"),
        os.path.join(_BASE_DIR, "H-AGENT", ".env"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("UPLOAD_API_TOKEN=") and not line.startswith("UPLOAD_API_TOKEN=#"):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            continue
    return os.environ.get("UPLOAD_API_TOKEN", "")


def _require_upload_auth(request: Request):
    """上传鉴权：
    - 本机（客户端 IP = 127.0.0.1）直接放行，方便浏览器在 localhost:8765 直传；
    - 同一局域网 PC（客户端 IP = RFC1918 私有地址 10/8、172.16/12、192.168/16）也直接放行，
      让同事浏览器经 LAN 访问 http://192.168.x.x:8765/ 上传 PDF 时无需手动带 token；
    - 公网来源（飞书 webhook / Cloudflare Tunnel 等）必须携带 Authorization: Bearer <UPLOAD_API_TOKEN>，
      否则 401/403 拒绝，避免保单 PDF 被任意人往系统里塞。
    """
    client_ip = _client_ip(request)
    try:
        ip = ipaddress.ip_address(client_ip)
        if ip.is_loopback or ip.is_private:
            return
    except ValueError:
        pass
    # 每次请求热读 .env 文件，写入 token 后无需重启服务即可生效
    token = _load_upload_token()
    if not token:
        raise HTTPException(status_code=403, detail="外部上传未授权：请在 .env 配置 UPLOAD_API_TOKEN")
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="上传令牌无效")


def _load_allowed_ips():
    """从 .env 实时读取 ALLOWED_IPS（公司网络白名单，CIDR 逗号分隔，热加载）。

    为空表示未配置白名单（fail-open，不拦截），避免误配把自己锁在门外。
    支持单 IP（203.0.113.7）与网段（203.0.113.0/24）混写。
    """
    candidates = [
        os.path.join(_BASE_DIR, ".env"),
        os.path.join(_BASE_DIR, "H-AGENT", ".env"),
    ]
    raw = ""
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ALLOWED_IPS=") and not line.startswith("ALLOWED_IPS=#"):
                        raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            continue
        if raw:
            break
    if not raw:
        raw = os.environ.get("ALLOWED_IPS", "")
    nets = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return nets


def _ip_whitelist_enabled() -> bool:
    """IP 白名单总开关。默认启用（True）；.env 设 IP_WHITELIST_ENABLED=false
    可整体关闭白名单，使公网地址对所有人开放（所有人可访问）。

    关闭后中间件直接放行，不再检查 ALLOWED_IPS。每次请求热读 .env，改完即时生效。
    """
    candidates = [
        os.path.join(_BASE_DIR, ".env"),
        os.path.join(_BASE_DIR, "H-AGENT", ".env"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("IP_WHITELIST_ENABLED=") and not line.startswith("IP_WHITELIST_ENABLED=#"):
                        val = line.split("=", 1)[1].strip().lower()
                        return val not in ("false", "0", "no", "off")
        except Exception:
            continue
    return True


def _client_ip(request: Request) -> str:
    """取真实访客 IP。Cloudflare Tunnel 会注入 CF-Connecting-IP；
    本机直连则回退到 X-Forwarded-For / X-Real-IP / socket 客户端地址。"""
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip().split(",")[0].strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xr = request.headers.get("X-Real-IP")
    if xr:
        return xr.strip()
    return request.client.host if request.client else "127.0.0.1"


@app.middleware("http")
async def ip_allowlist_middleware(request: Request, call_next):
    """公司网络 IP 白名单：仅允许「本机」+「白名单内 IP」访问 Web 控制台与普通接口。

    - 上传接口 /api/upload 保持令牌鉴权、不限 IP（飞书 webhook 来自飞书云端，
      不在公司网段，靠 UPLOAD_API_TOKEN 保护即可，否则飞书自动化会被一起挡掉）。
    - 白名单未配置（ALLOWED_IPS 为空）时 fail-open，不拦截，避免误锁自己。
    """
    client = _client_ip(request)
    path = request.url.path

    # 本机始终放行：控制台在 PC 本地 127.0.0.1:8765 直连不受影响
    try:
        if client in ("127.0.0.1", "::1") or ipaddress.ip_address(client).is_loopback:
            return await call_next(request)
    except ValueError:
        pass

    # 上传接口：令牌鉴权即可，跳过 IP 白名单（飞书云端调用）
    if path.startswith("/api/upload"):
        return await call_next(request)

    # 健康检查保持开放，便于隧道/监控探活
    if path == "/api/health":
        return await call_next(request)

    # 白名单总开关：关闭时对所有外部访客放行（所有人可访问）
    # 注意：/api/upload 的令牌鉴权独立于此开关，始终生效
    if not _ip_whitelist_enabled():
        return await call_next(request)

    allowed = _load_allowed_ips()
    if not allowed:
        return await call_next(request)

    try:
        addr = ipaddress.ip_address(client)
    except ValueError:
        return JSONResponse(status_code=403, content={"detail": "Forbidden: 无法识别的客户端地址"})

    if any(addr in net for net in allowed):
        return await call_next(request)

    return JSONResponse(
        status_code=403,
        content={"detail": "Forbidden: 仅限公司网络访问，当前 IP 不在白名单"},
    )


@app.get("/api/my-ip")
async def my_ip(request: Request):
    """诊断用：返回白名单中间件会看到的真实访客 IP（经 Cloudflare Tunnel 即 CF-Connecting-IP）。

    在公司网络下打开此接口即可确认公司出口 IP，把该 IP 所在网段填入 .env 的
    ALLOWED_IPS（CIDR，逗号分隔）后重启服务即生效。仅回显调用方自身 IP，无敏感信息。
    """
    return {
        "client_ip": _client_ip(request),
        "note": "将此 IP 所在网段填入 .env 的 ALLOWED_IPS（如 203.0.113.0/24），重启服务生效",
    }


@app.post("/api/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(None),
    file: UploadFile = File(None),
):
    """上传多个 PDF 文件并提取被保人员信息（兼容字段名 file / files）"""
    global _latest_results

    _require_upload_auth(request)

    received = list(files or [])
    if file is not None:
        received.append(file)
    if not received:
        raise HTTPException(status_code=400, detail="未上传文件")

    saved_paths = []
    tmp_dir = tempfile.mkdtemp(prefix="insurance_upload_")

    for f in received:
        raw_name = f.filename or ""
        filename = _fix_filename(raw_name)
        if not filename.lower().endswith(".pdf"):
            continue
        save_path = os.path.join(tmp_dir, filename)
        with open(save_path, "wb") as out:
            content = await f.read()
            out.write(content)
        saved_paths.append(save_path)

    if not saved_paths:
        raise HTTPException(status_code=400, detail="未找到 PDF 文件")

    # 处理文件
    results = process_files(saved_paths)
    _latest_results = results

    # 构建返回数据
    summary = []
    for r in results:
        if r.get("error"):
            summary.append({
                "file_name": r.get("file_name", ""),
                "error": r["error"],
                "persons": [],
            })
            continue
        persons = r.get("insured_persons", [])
        add_count = sum(1 for p in persons if p.get("modification_type") == "增保")
        remove_count = sum(1 for p in persons if p.get("modification_type") == "减保")
        summary.append({
            "file_name": r.get("file_name", ""),
            "insurance_company": r.get("insurance_company", ""),
            "policy_number": r.get("policy_number", ""),
            "overall_start_date": r.get("overall_start_date", ""),
            "overall_end_date": r.get("overall_end_date", ""),
            "persons_count": len(persons),
            "add_count": add_count,
            "remove_count": remove_count,
            "persons": persons,
        })

    total_persons = sum(s.get("persons_count", 0) for s in summary)
    total_add = sum(s.get("add_count", 0) for s in summary)
    total_remove = sum(s.get("remove_count", 0) for s in summary)

    return JSONResponse({
        "success": True,
        "total_files": len(summary),
        "total_persons": total_persons,
        "total_add": total_add,
        "total_remove": total_remove,
        "results": summary,
    })


@app.get("/api/download/csv")
async def download_csv():
    """下载 CSV 表格"""
    if not _latest_results:
        raise HTTPException(status_code=404, detail="无提取结果，请先上传文件")

    rows = results_to_rows(_latest_results)
    if not rows:
        raise HTTPException(status_code=404, detail="无可导出的数据")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)

    filename = f"被保人员清单_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    encoded_filename = quote(filename)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


@app.get("/api/download/xlsx")
async def download_xlsx():
    """下载 Excel 表格"""
    if not _latest_results:
        raise HTTPException(status_code=404, detail="无提取结果，请先上传文件")

    rows = results_to_rows(_latest_results)
    if not rows:
        raise HTTPException(status_code=404, detail="无可导出的数据")

    wb = Workbook()
    ws = wb.active
    ws.title = "被保人员清单"

    # 表头样式
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # 写表头
    for col_idx, field in enumerate(CSV_FIELDS, 1):
        cell = ws.cell(row=1, column=col_idx, value=field)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 写数据
    data_font = Font(name="微软雅黑", size=10)
    add_fill = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")  # 浅红
    remove_fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")  # 浅蓝

    for row_idx, row in enumerate(rows, 2):
        for col_idx, field in enumerate(CSV_FIELDS, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row.get(field, ""))
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")
            # 增保/减保行着色
            if field == "批改类型":
                if row.get(field) == "增保":
                    cell.fill = add_fill
                elif row.get(field) == "减保":
                    cell.fill = remove_fill

    # 自动列宽
    col_widths = {
        "姓名": 12, "证件号码": 24, "证件类型": 10, "出生日期": 14,
        "所属公司": 28, "批改类型": 10,
        "起始时间": 14, "起止时间": 14,
        "岗位名称": 16, "保险公司": 20, "保单号": 30, "来源文件": 40,
    }
    for col_idx, field in enumerate(CSV_FIELDS, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = col_widths.get(field, 15)

    # 冻结首行
    ws.freeze_panes = "A2"

    # 保存到内存
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"被保人员清单_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    encoded_filename = quote(filename)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


@app.get("/api/policy-library")
async def get_policy_library():
    """获取保单文件库状态（合并索引元数据 + 文件系统 mtime/size）"""
    records = []
    # 用 dict 按 file_name 索引索引元数据；文件系统 mtime 优先用于「上传日期」展示
    meta_by_name = {r.file_name: r for r in _policy_library.records}
    base_dir = _policy_library.base_dir
    try:
        fs_files = os.listdir(base_dir)
    except Exception:
        fs_files = []
    # 文件系统有的所有 PDF（即使索引里没有也展示，例如手工复制进去的）
    all_names = set(meta_by_name.keys()) | {f for f in fs_files if f.lower().endswith(".pdf")}
    for name in sorted(all_names, key=lambda x: x.lower()):
        full_path = os.path.join(base_dir, name)
        meta = meta_by_name.get(name)
        try:
            stat_info = os.stat(full_path)
            mtime_ts = int(stat_info.st_mtime)
            size_bytes = stat_info.st_size
        except OSError:
            mtime_ts = 0
            size_bytes = 0
        records.append({
            "file_name": name,
            "policy_type": meta.policy_type if meta else "",
            "policy_number": meta.policy_number if meta else "",
            "company": meta.company if meta else "",
            "insurance_company": meta.insurance_company if meta else "",
            "start_date": meta.start_date if meta else "",
            "end_date": meta.end_date if meta else "",
            "persons_count": meta.persons_count if meta else 0,
            "upload_date_ts": mtime_ts,        # 文件 mtime，秒级时间戳
            "size_bytes": size_bytes,
            "in_index": meta is not None,
        })
    # 按 mtime 降序（最新上传在前）
    records.sort(key=lambda x: x["upload_date_ts"], reverse=True)
    return {"records": records, "total": len(records), "base_dir": base_dir}


@app.get("/api/policy-library/download/{filename}")
async def download_policy_pdf(filename: str):
    """从保单库下载指定 PDF（其他 PC 也能下载）。

    安全约束：
    - filename 必须仅含 basename（不允许路径分隔符 / `\\` / `..`），防目录穿越；
    - 文件必须存在于 base_dir 下且以 .pdf 结尾；
    - 中文文件名用 RFC 5987 filename* 编码，避免 Content-Disposition 乱码。
    """
    base_dir = _policy_library.base_dir
    # 仅取 basename，丢弃任何路径前缀
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name or ".." in safe_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持下载 PDF 文件")
    full_path = os.path.join(base_dir, safe_name)
    # 二次校验：解析后的绝对路径必须在 base_dir 之下
    try:
        real_base = os.path.realpath(base_dir)
        real_path = os.path.realpath(full_path)
        if not real_path.startswith(real_base + os.sep) and real_path != real_base:
            raise HTTPException(status_code=400, detail="非法路径")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="路径校验失败")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")
    # 用 FileResponse 让浏览器直接弹出下载（attachment 触发下载而非预览）
    encoded_filename = quote(safe_name)
    return FileResponse(
        full_path,
        media_type="application/pdf",
        filename=safe_name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@app.get("/")
async def index():
    """返回前端页面"""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


# ==================== 保险到期提醒 ====================

class SmsConfigSchema(BaseModel):
    """短信配置请求体"""
    enabled: bool = False
    provider: str = "aliyun"
    access_key_id: str = ""
    access_key_secret: str = ""
    sdk_app_id: str = ""
    sign_name: str = ""
    template_code: str = ""
    region: str = ""
    phone_numbers: list[str] = []
    template_content: str = ""   # 短信正文模板（可在前端编辑）


class ReminderConfigSchema(BaseModel):
    """提醒配置请求体"""
    sender_email: str = ""
    sender_auth: str = ""
    recipient_emails: list[str] = []
    enabled: bool = True
    check_days: Optional[list[int]] = None
    smtp_host: str = ""
    smtp_port: int = 0
    sms: SmsConfigSchema = SmsConfigSchema()
    # ===== 邮件文案（可在前端编辑，后台不写死）=====
    subject_template: str = ""
    title: str = ""
    subtitle_template: str = ""
    footer: str = ""
    expiry_title: str = ""
    expiry_subtitle_template: str = ""


@app.get("/api/reminder/config")
async def get_reminder_config():
    """获取提醒配置（授权码脱敏）"""
    config = load_config()
    return JSONResponse(get_config_for_response(config))


@app.put("/api/reminder/config")
async def update_reminder_config(body: ReminderConfigSchema):
    """更新提醒配置"""
    config = load_config()
    email = config.setdefault("email", {})
    if body.sender_email:
        email["sender_email"] = body.sender_email
    if body.sender_auth and body.sender_auth != "****":
        email["sender_auth"] = body.sender_auth
    if body.recipient_emails:
        email["recipient_emails"] = body.recipient_emails
    email["enabled"] = body.enabled
    if body.check_days is not None:
        config["check_days"] = body.check_days
    if body.smtp_host:
        email["smtp_host"] = body.smtp_host
    if body.smtp_port:
        email["smtp_port"] = body.smtp_port

    # 邮件文案（前端可编辑，留空则不覆盖默认值）
    if body.subject_template:
        email["subject_template"] = body.subject_template
    if body.title:
        email["title"] = body.title
    if body.subtitle_template:
        email["subtitle_template"] = body.subtitle_template
    if body.footer:
        email["footer"] = body.footer
    if body.expiry_title:
        email["expiry_title"] = body.expiry_title
    if body.expiry_subtitle_template:
        email["expiry_subtitle_template"] = body.expiry_subtitle_template

    # 保存短信配置
    sms = config.setdefault("sms", {})
    sms["enabled"] = body.sms.enabled
    sms["provider"] = body.sms.provider
    if body.sms.access_key_id:
        sms["access_key_id"] = body.sms.access_key_id
    if body.sms.access_key_secret and body.sms.access_key_secret != "****":
        sms["access_key_secret"] = body.sms.access_key_secret
    if body.sms.sdk_app_id:
        sms["sdk_app_id"] = body.sms.sdk_app_id
    if body.sms.sign_name:
        sms["sign_name"] = body.sms.sign_name
    if body.sms.template_code:
        sms["template_code"] = body.sms.template_code
    if body.sms.region:
        sms["region"] = body.sms.region
    if body.sms.phone_numbers:
        sms["phone_numbers"] = body.sms.phone_numbers
    if body.sms.template_content:
        sms["template_content"] = body.sms.template_content

    if save_config(config):
        return JSONResponse({"success": True, "message": "配置已保存"})
    raise HTTPException(status_code=500, detail="保存配置失败")


@app.post("/api/reminder/test-sms")
async def test_reminder_sms():
    """发送测试短信

    用短信模板 + 测试变量发送一条测试短信。
    短信服务商 SDK 待提供凭证后对接，当前返回模板和变量预览。
    """
    from insurance_agent.tools.insurance_reminder import SMS_TEMPLATE
    from insurance_agent.tools.sms_sender import send_sms

    config = load_config()
    sms = config.get("sms", {})
    if not sms.get("enabled", False):
        raise HTTPException(status_code=400, detail="短信通知已禁用")

    # 短信正文模板取配置（前端可编辑），缺省用后台默认
    sms_template = sms.get("template_content") or SMS_TEMPLATE

    # 构造测试消息
    test_messages = [{
        "project": "测试项目",
        "names": "张三、李四",
        "count": "2",
    }]

    result = send_sms(sms, test_messages)
    return JSONResponse({
        **result,
        "sms_template": sms_template,
        "sample_message": test_messages[0],
    })


@app.post("/api/reminder/check")
async def check_reminder():
    """手动触发保险到期提醒检查"""
    try:
        result = run_reminder_check()
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"提醒检查失败: {e}")


@app.post("/api/reminder/check-expiry")
async def check_expiry():
    """手动触发到期提醒检查（查询还有 N 天到期的人员并发送邮件）"""
    try:
        cfg = scheduler_mod.load_scheduler_config()
        ahead_days = cfg.get("expiry_ahead_days", 3)
        result = run_expiry_check(ahead_days=ahead_days)
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"到期提醒检查失败: {e}")


@app.get("/api/reminder/expiring-db")
async def list_expiring_db(ahead_days: int = 3):
    """查看即将到期的人员（数据库数据源，不发送邮件）

    Args:
        ahead_days: 提前天数，查询"还有 N 天到期"的人员
    """
    expiring = find_expiring_from_db(ahead_days)
    target_date = (datetime.now() + timedelta(days=ahead_days)).strftime("%Y-%m-%d")
    return JSONResponse({
        "check_date": datetime.now().strftime("%Y-%m-%d"),
        "ahead_days": ahead_days,
        "target_date": target_date,
        "expiring_count": len(expiring),
        "expiring_persons": expiring,
    })


@app.get("/api/reminder/history")
async def get_reminder_history():
    """获取最近一次检查记录"""
    config = load_config()
    last_result = config.get("last_result")
    if not last_result:
        return JSONResponse({})
    return JSONResponse(last_result)


@app.post("/api/reminder/test-email")
async def test_reminder_email():
    """发送测试邮件，验证邮箱配置是否正确"""
    config = load_config()
    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled", True):
        raise HTTPException(status_code=400, detail="邮件通知已禁用")
    from insurance_agent.domain import InsuredPerson
    today = datetime.now().strftime("%Y-%m-%d")
    test_person = {
        "name": "测试用户", "id_number": "110101199001011234", "id_type": "身份证",
        "birth_date": "1990-01-01", "company": "测试公司", "modification_type": "增保",
        "start_date": today, "end_date": today, "job_title": "测试岗位",
        "insurance_company": "测试保险公司", "policy_number": "TEST20240001", "file_name": "测试文件.pdf",
    }
    result = send_reminder_email([test_person], today, email_cfg)
    return JSONResponse(result)


@app.get("/api/reminder/expiring")
async def list_expiring():
    """查看即将到期的人员（不发送邮件）"""
    persons = load_persons_from_json()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    expiring = find_expiring_tomorrow(persons)
    return JSONResponse({
        "check_date": datetime.now().strftime("%Y-%m-%d"),
        "target_date": tomorrow,
        "total_in_system": len(persons),
        "expiring_count": len(expiring),
        "expiring_persons": expiring,
    })


# ==================== 今日打卡数据 + 保险覆盖检查 ====================

@app.get("/api/punch/records")
async def get_punch_records(punch_date: str = None):
    """查询打卡数据

    Args:
        punch_date: 打卡日期（默认今天）

    测试模式：当 ``.reminder_config.json`` 的 ``punch_table_for_sms`` 字段不为空且
    不等于 ``punch_records`` 时，从对应副本表读取（默认仍读生产表）。
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")
    punch_table = "punch_records"
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "..", ".reminder_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_table = (json.load(f).get("punch_table_for_sms") or "").strip()
            if cfg_table and cfg_table != "punch_records":
                if cfg_table == "punch_records_test" or cfg_table.startswith("punch_records_backup_"):
                    punch_table = cfg_table
    except Exception as e:  # noqa: BLE001
        print(f"[punch/records] read punch_table_for_sms failed: {e}", flush=True)

    records = db.get_punch_records(punch_date, limit=10000, table=punch_table)
    return JSONResponse({
        "success": True,
        "punch_date": punch_date,
        "total": len(records),
        "punch_table": punch_table,
        "records": records,
    })


@app.post("/api/punch/sync")
async def sync_punch():
    """手动同步今日打卡数据"""
    # 打卡同步功能��关：关闭后禁止从 ERP 拉取打卡数据
    sched_cfg = scheduler_mod.load_scheduler_config()
    if not sched_cfg.get("punch_sync_enabled", True):
        return JSONResponse({
            "success": False,
            "disabled": True,
            "error": "打卡同步功能已关闭，请在「定时任务配置」中重新启用后再同步",
        })

    punch_date = datetime.now().strftime("%Y-%m-%d")
    try:
        result = coverage_check.sync_punch_data(_session_manager, punch_date)
        return JSONResponse(result)
    except Exception as e:
        # "attempt to write a readonly database" 是沙箱环境特有（watchdog 子进程
        # 继承 pythonw token），不影响生产 Windows 桌面。统一返回 200 让前端能解析。
        if "readonly database" in str(e):
            return JSONResponse({
                "success": False,
                "readonly_db": True,
                "error": "数据库写入权限受限（沙箱环境特征），生产 Windows 不受影响。",
            })
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"同步失败: {e}")


@app.patch("/api/punch/record/{record_id}")
async def update_punch_record(record_id: int, body: dict):
    """更新单条打卡记录的可编辑字段（项目经理/手机号/邮箱）

    仅允许更新 project_manager / manager_phone / manager_email。
    """
    allowed = {"project_manager", "manager_phone", "manager_email"}
    updates = {k: v for k, v in (body or {}).items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="无可更新的合法字段")
    try:
        ok = db.update_punch_record_fields(record_id, updates)
        if not ok:
            raise HTTPException(status_code=404, detail="记录不存在或更新失败")
        return JSONResponse({"success": True, "record_id": record_id, "updated": updates})
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")


@app.post("/api/punch/check")
async def check_coverage():
    """检查打卡人员保险覆盖情况

    测试模式：``.reminder_config.json`` 的 ``punch_table_for_sms`` 字段不为空且
    不等于 ``punch_records`` 时，从对应副本表读取经理联系方式（默认仍读生产表）。
    """
    punch_date = datetime.now().strftime("%Y-%m-%d")
    punch_table = "punch_records"
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "..", ".reminder_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_table = (json.load(f).get("punch_table_for_sms") or "").strip()
            if cfg_table and cfg_table != "punch_records":
                if cfg_table == "punch_records_test" or cfg_table.startswith("punch_records_backup_"):
                    punch_table = cfg_table
    except Exception as e:  # noqa: BLE001
        print(f"[punch/check] read punch_table_for_sms failed: {e}", flush=True)
    try:
        result = coverage_check.check_insurance_coverage(punch_date, punch_table=punch_table)
        result["punch_table"] = punch_table
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"检查失败: {e}")


@app.get("/api/punch/export-uninsured")
async def export_uninsured():
    """导出无正常保单人员清单为 Excel

    测试模式：``.reminder_config.json`` 的 ``punch_table_for_sms`` 字段决定是否
    从副本表读取经理联系方式（默认仍读生产表）。
    """
    punch_date = datetime.now().strftime("%Y-%m-%d")
    punch_table = "punch_records"
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "..", ".reminder_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_table = (json.load(f).get("punch_table_for_sms") or "").strip()
            if cfg_table and cfg_table != "punch_records":
                if cfg_table == "punch_records_test" or cfg_table.startswith("punch_records_backup_"):
                    punch_table = cfg_table
    except Exception as e:  # noqa: BLE001
        print(f"[punch/export-uninsured] read punch_table_for_sms failed: {e}", flush=True)
    result = coverage_check.check_insurance_coverage(punch_date, punch_table=punch_table)
    uninsured = result.get("uninsured_list", [])

    if not uninsured:
        raise HTTPException(status_code=404, detail="当前无「无保险」人员")

    wb = Workbook()
    ws = wb.active
    ws.title = "无保险人员清单"

    # 表头样式
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="E53E3E", end_color="E53E3E", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # 列定义：Excel 表头 → uninsured 字段
    columns = [
        ("序号", None),
        ("姓名", "name"),
        ("身份证号", "id_number"),
        ("项目名称", "project_name"),
        ("项目经理", "project_manager"),
        ("手机号", "manager_phone"),
        ("邮箱", "manager_email"),
        ("班组", "team_name"),
        ("劳务公司", "supplier_name"),
        ("劳务分类", "category_name"),
    ]

    # 写表头
    for col_idx, (label, _) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 写数据
    data_font = Font(name="微软雅黑", size=10)
    for row_idx, p in enumerate(uninsured, 2):
        for col_idx, (label, key) in enumerate(columns, 1):
            if key is None:
                value = row_idx - 1  # 序号
            else:
                value = p.get(key, "") or ""
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    # 列宽
    col_widths = {"序号": 6, "姓名": 12, "身份证号": 22, "项目名称": 40, "项目经理": 14, "手机号": 16, "邮箱": 26, "班组": 14, "劳务公司": 28, "劳务分类": 12}
    for col_idx, (label, _) in enumerate(columns, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = col_widths.get(label, 15)

    ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"无保险人员清单_{punch_date}.xlsx"
    encoded_filename = quote(filename)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


@app.post("/api/daily-check")
async def daily_check(force: bool = False):
    """发送提醒信息：给对应项目的项目经理推送「打卡但无正常保单」的人员数据短信和邮件。

    流程：同步打卡 → 保险覆盖对比 → 每经理一封邮件 + 每经理一条短信 + 汇总邮件到固定收件人。
    force=true 时跳过「今日已发送过则跳过」的保护，强制重发（仅调试用）。
    """
    try:
        result = run_daily_check(
            session_manager=_session_manager,
            force=force,
        )
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发送提醒信息失败: {e}")


# ==================== 实时打卡事件接入（MQ 桥接 / HTTP 适配） ====================

class PunchEventItem(BaseModel):
    """单条打卡事件（兼容 ERP 驼峰/蛇形命名，后台自动规范化）"""
    id: Optional[Any] = None
    erp_id: Optional[Any] = None
    memberId: Optional[Any] = None
    member_id: Optional[Any] = None
    memberName: Optional[Any] = None
    member_name: Optional[Any] = None
    name: Optional[Any] = None
    identificationNumber: Optional[Any] = None
    identification_number: Optional[Any] = None
    id_number: Optional[Any] = None
    age: Optional[Any] = None
    projectName: Optional[Any] = None
    project_name: Optional[Any] = None
    teamName: Optional[Any] = None
    team_name: Optional[Any] = None
    supplierName: Optional[Any] = None
    supplier_name: Optional[Any] = None
    categoryName: Optional[Any] = None
    category_name: Optional[Any] = None
    examinationStatusName: Optional[Any] = None
    examination_status: Optional[Any] = None
    telephone: Optional[Any] = None
    phone: Optional[Any] = None


class PunchEventsBody(BaseModel):
    """批量打卡事件入参。

    ERP（或 MQ 桥接程序）每次推送可包含多条（瞬时多台打卡机同时打卡）。
    source 仅作日志标记。
    """
    events: Optional[list] = None
    event: Optional[dict] = None
    source: Optional[str] = "erp"


@app.post("/api/punch/events")
async def ingest_punch_events(body: PunchEventsBody):
    """接收 ERP 实时打卡事件（MQ 异步推送的 HTTP 适配入口）

    ERP 团队建议用「现有 MQ 消息队列异步推送」。落地方式：
    - 生产环境：在 ERP/MQ 侧部署一个轻量桥接程序订阅 MQ 主题，把消息转调本接口；
      或未来在智能体进程内直接订阅 MQ，调用 submit_punch_events 即可（下游逻辑复用）。
    - 本接口立即把事件放入进程内队列并返回，不阻塞 ERP 推送方；真正的入库、
      保险核对、通知由后台消费者线程按滑动窗口批处理，天然抗突发流量。

    返回：{"accepted": n, "queued": true}
    """
    events = []
    if body.events:
        events.extend(body.events)
    if body.event:
        events.append(body.event)
    if not events:
        raise HTTPException(status_code=400, detail="events 与 event 不能同时为空")
    try:
        n = submit_punch_events(events)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"事件入队失败: {e}")
    return JSONResponse({"accepted": n, "queued": True, "source": body.source or "erp"})


@app.get("/api/realtime/status")
async def realtime_status():
    """实时消费者运行态（队列积压、批次数、经理缓存、错误数等）"""
    try:
        return JSONResponse(get_realtime_status())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


# ==================== 飞书多维表格 Webhook 集成 ====================

@app.get("/api/feishu-webhook/status")
async def feishu_webhook_status():
    """获取飞书 webhook pusher 状态（Token 自动脱敏）。"""
    p = get_feishu_pusher()
    if p is None:
        return JSONResponse({"initialized": False, "message": "pusher 未初始化（重启服务生效）"})
    return JSONResponse({"initialized": True, **p.get_status(mask_token=True)})


@app.post("/api/feishu-webhook/reload")
async def feishu_webhook_reload():
    """热加载 .feishu_webhook.json（编辑 Token/URL 后无需重启）。"""
    p = get_feishu_pusher()
    if p is None:
        raise HTTPException(status_code=503, detail="pusher 未初始化")
    cfg = p.reload_config()
    token = cfg.get("bearer_token", "")
    masked = (token[:4] + "***" + token[-4:]) if len(token) > 8 else "***"
    return JSONResponse({"ok": True, "enabled": cfg.get("enabled"), "token_preview": masked})


@app.post("/api/feishu-webhook/test")
async def feishu_webhook_test():
    """发送一条测试数据到飞书 webhook（用占位人员数据），便于验证 Token/IP/字段映射。"""
    from insurance_agent.tools.feishu_webhook_pusher import push_uninsured_person
    test_record = {
        "name": "测试-飞书推送",
        "id_number": "TEST_PING_NO_REALTIME_ID",
        "project_name": "测试项目-请忽略",
        "team_name": "测试班组",
        "supplier_name": "测试劳务公司",
        "category_name": "测试工种",
        "project_manager": "测试经理",
        "manager_phone": "13800000000",
        "manager_email": "test@example.com",
        "punch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "punch_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "test",
    }
    enqueued = push_uninsured_person(test_record, source="test")
    return JSONResponse({
        "ok": enqueued,
        "message": "已入队，worker 异步推送" if enqueued else "未入队（请检查 .feishu_webhook.json 中 enabled=true 且 token 已替换）",
        "record": test_record,
    })


@app.post("/api/summary/trigger")
async def summary_trigger(period: str = "morning", force: bool = True):
    """手动触发未参保人员汇总（用于测试 + 紧急补发）。

    Args:
        period: "morning" 或 "afternoon"（仅用于邮件标题区分）
        force: True=绕过 scheduler 同日去重，强制发送
    """
    if period not in ("morning", "afternoon"):
        raise HTTPException(status_code=400, detail="period 必须是 morning 或 afternoon")
    try:
        result = run_uninsured_summary(
            session_manager=_session_manager,
            period=period,
            force=force,
        )
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"汇总发送失败: {e}")


# ==================== 通知发送审计日志 ====================

@app.get("/api/audit/notifications")
async def get_audit_notifications(
    limit: int = 200,
    channel: Optional[str] = None,
    kind: Optional[str] = None,
    date: Optional[str] = None,
    only_failures: bool = False,
):
    """读取通知发送审计日志（打卡无保险提醒的所有短信/邮件发送记录）。

    Args:
        limit: 返回的最大记录数（默认 200，新→旧）
        channel: realtime / daily_check / summary_morning / summary_afternoon / expiry_reminder
        kind: sms / email
        date: 仅查指定日期 YYYY-MM-DD（默认全部）
        only_failures: True=仅看失败记录
    """
    from insurance_agent.tools.notification_audit import read_audit, stats_today
    date_from = (date + " 00:00:00") if date else None
    date_to = (date + " 23:59:59") if date else None
    rows = read_audit(
        limit=limit, channel=channel, kind=kind,
        date_from=date_from, date_to=date_to,
        only_failures=only_failures,
    )
    stats = stats_today()
    return JSONResponse({
        "ok": True,
        "total": len(rows),
        "stats_today": stats,
        "items": rows,
    })


@app.post("/api/audit/notifications/clear")
async def clear_audit_notifications(older_than_days: int = 0):
    """清理通知审计日志。

    Args:
        older_than_days: 0=清空全部；>0=仅清理 N 天前的
    """
    from insurance_agent.tools.notification_audit import clear_audit
    n = clear_audit(older_than_days)
    return JSONResponse({"ok": True, "deleted": n})


@app.get("/api/audit/notifications/export")
async def export_audit_notifications(limit: int = 1000):
    """导出审计日志为 CSV（便于下载分析）。"""
    from insurance_agent.tools.notification_audit import read_audit
    import csv
    import io

    rows = read_audit(limit=limit)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for r in rows:
            row_out = dict(r)
            # list 字段转字符串，避免 CSV 单元格报错
            for k, v in row_out.items():
                if isinstance(v, list):
                    row_out[k] = ";".join(str(x) for x in v)
            writer.writerow(row_out)
    csv_text = buf.getvalue()
    return JSONResponse({
        "ok": True,
        "count": len(rows),
        "csv": csv_text,
    })


# ==================== 定时任务配置 ====================

class SchedulerConfigSchema(BaseModel):
    enabled: Optional[bool] = None
    sync_time: Optional[str] = None
    alert_enabled: Optional[bool] = None
    punch_sync_enabled: Optional[bool] = None
    expiry_time: Optional[str] = None
    expiry_ahead_days: Optional[int] = None
    expiry_enabled: Optional[bool] = None


@app.get("/api/scheduler/config")
async def get_scheduler_config():
    """获取定时任务配置"""
    return JSONResponse(scheduler_mod.load_scheduler_config())


@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """获取定时任务运行状态"""
    sched = scheduler_mod.get_scheduler()
    if sched is None:
        return JSONResponse({"running": False, "message": "调度器未创建"})
    return JSONResponse({
        "running": bool(sched._running),
        "last_run_date": sched._last_run_date,
        "last_run_dates": sched._last_run_dates,
        "check_interval": sched._check_interval,
        "tasks": [{"name": t["name"], "time_key": t["time_key"]} for t in sched._tasks],
    })


@app.put("/api/scheduler/config")
async def update_scheduler_config(body: SchedulerConfigSchema):
    """更新定时任务配置（仅更新传入的字段）"""
    config = scheduler_mod.load_scheduler_config()
    updates = body.dict(exclude_none=True)
    if not updates:
        return JSONResponse({"success": True, "message": "无更新内容", "config": config})
    config.update(updates)
    if scheduler_mod.save_scheduler_config(config):
        return JSONResponse({"success": True, "message": "配置已保存", "config": config})
    raise HTTPException(status_code=500, detail="保存配置失败")


@app.get("/api/db/stats")
async def get_db_stats():
    """获取数据库统计信息"""
    return JSONResponse(db.db_stats())


# ==================== 保单人员数据管理 ====================

def _personnel_to_row(p: dict) -> dict:
    """数据库记录 → 中文表头行（含主键 id，用于编辑/删除）"""
    row = {"id": p.get("id")}
    for label, key in PERSONNEL_FIELDS:
        row[label] = p.get(key, "") or ""
    return row


@app.get("/api/personnel")
async def get_personnel():
    """查询全部保单人员数据"""
    try:
        # 先刷新到期状态：已到起止日期的自动标记为失效
        db.refresh_expired_status()
        persons = db.get_insurance_personnel()
        rows = [_personnel_to_row(p) for p in persons]
        return JSONResponse({
            "success": True,
            "total": len(rows),
            "records": rows,
        })
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        print("[api/personnel] ERROR:", e, flush=True)
        _tb.print_exc()
        raise


def _parse_personnel_excel(content: bytes) -> list[dict]:
    """解析保单人员 Excel，返回人员列表（统一表头字段）

    支持字段：姓名/证件号码/证件类型/出生日期/所属公司/状态/起始时间/起止时间/岗位名称/保险公司/保单号/来源文件
    """
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {e}")

    # 读取表头，建立 列名→列索引 映射
    header_row = None
    header_map = {}  # 中文列名 → 列索引（0-based）
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        header_row = row
        break

    if not header_row:
        raise HTTPException(status_code=400, detail="Excel 无表头")

    for idx, cell in enumerate(header_row):
        if cell is not None:
            header_map[str(cell).strip()] = idx

    # 校验必需字段
    if "姓名" not in header_map or "证件号码" not in header_map:
        raise HTTPException(status_code=400, detail="Excel 需包含「姓名」和「证件号码」列")

    # 解析数据行
    persons = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        def _get(label):
            idx = header_map.get(label)
            if idx is None or idx >= len(row):
                return ""
            val = row[idx]
            return "" if val is None else str(val).strip()
        # 姓名和证件号码必须有
        name = _get("姓名")
        id_num = _get("证件号码")
        if not name and not id_num:
            continue
        # 状态：只接受白名单 {正常, 失效}（2026-09-16 加固）
        # Excel 的「状态」列历史上有被填成批改类型（增保/减保）的情况，
        # 直接入库会污染 pol 数据，导致参保检测漏匹配 → 误发通知（段小平事件）。
        end_date = _get("起止时间")
        raw_status = _get("状态")
        today = datetime.now().strftime("%Y-%m-%d")
        status = db.normalize_person_status(raw_status, end_date, today) if raw_status else (
            "失效" if (end_date and end_date < today) else "正常"
        )
        person = {
            "name": name,
            "id_number": id_num,
            "id_type": _get("证件类型") or "身份证",
            "birth_date": _get("出生日期"),
            "company": _get("所属公司"),
            "status": status,
            "start_date": _get("起始时间"),
            "end_date": _get("起止时间"),
            "job_title": _get("岗位名称"),
            "insurance_company": _get("保险公司"),
            "policy_number": _get("保单号"),
            "source_file": _get("来源文件"),
        }
        persons.append(person)

    if not persons:
        raise HTTPException(status_code=400, detail="Excel 中没有有效的人员数据")
    return persons


async def _read_personnel_excel(file: UploadFile) -> list[dict]:
    """读取并解析上传的 Excel 文件"""
    filename = _fix_filename(file.filename or "")
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    return _parse_personnel_excel(content)


@app.post("/api/personnel/upload-excel")
async def upload_personnel_excel(file: UploadFile = File(...)):
    """上传 Excel 模板文件，替换全部保单人员数据"""
    persons = await _read_personnel_excel(file)

    # 替换：清空旧数据，写入新数据
    removed = db.clear_insurance_personnel()
    stored = db.upsert_insurance_personnel(persons)

    return JSONResponse({
        "success": True,
        "message": f"替换成功：清空 {removed} 条旧数据，导入 {stored} 条新数据",
        "total": stored,
        "removed": removed,
    })


@app.post("/api/personnel/upload-excel-add")
async def upload_personnel_excel_add(file: UploadFile = File(...)):
    """上传 Excel 模板文件，新增保单人员数据（同名同身份证则更新最新起止日期）"""
    persons = await _read_personnel_excel(file)

    result = db.add_insurance_personnel(persons)

    return JSONResponse({
        "success": True,
        "message": f"新增成功：新增 {result['added']} 条，更新 {result['updated']} 条",
        "added": result["added"],
        "updated": result["updated"],
    })


class ManualAddSchema(BaseModel):
    """手动添加保单人员请求体"""
    name: str = ""
    id_number: str = ""
    id_type: str = "身份证"
    birth_date: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    job_title: str = ""
    insurance_company: str = ""
    policy_number: str = ""
    status: str = "正常"


@app.post("/api/personnel/manual-add")
async def manual_add_personnel(body: ManualAddSchema):
    """手动添加单条保单人员数据（少量无法识别的保单格式）"""
    name = body.name.strip()
    id_num = body.id_number.strip()

    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if not id_num:
        raise HTTPException(status_code=400, detail="证件号码不能为空")

    # 出生日期为空时从身份证号自动提取（第7-14位）
    birth_date = body.birth_date.strip()
    if not birth_date and len(id_num) >= 14 and id_num[6:14].isdigit():
        birth_date = f"{id_num[6:10]}-{id_num[10:12]}-{id_num[12:14]}"

    # 状态：未指定或为"正常"时，根据起止日期判断是否已到期
    status = body.status.strip() or "正常"
    end_date = body.end_date.strip()
    if status == "正常" and end_date:
        today = datetime.now().strftime("%Y-%m-%d")
        if end_date < today:
            status = "失效"

    person = {
        "name": name,
        "id_number": id_num,
        "id_type": body.id_type.strip() or "身份证",
        "birth_date": birth_date,
        "company": body.company.strip(),
        "start_date": body.start_date.strip(),
        "end_date": end_date,
        "job_title": body.job_title.strip(),
        "insurance_company": body.insurance_company.strip(),
        "policy_number": body.policy_number.strip(),
        "status": status,
    }

    result = db.add_insurance_personnel([person])

    return JSONResponse({
        "success": True,
        "message": f"添加成功：新增 {result['added']} 条，更新 {result['updated']} 条",
        "added": result["added"],
        "updated": result["updated"],
    })


@app.put("/api/personnel/{person_id}")
async def update_personnel(person_id: int, body: ManualAddSchema):
    """编辑保单人员数据"""
    name = body.name.strip()
    id_num = body.id_number.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if not id_num:
        raise HTTPException(status_code=400, detail="证件号码不能为空")

    # 出生日期为空时从身份证号自动提取
    birth_date = body.birth_date.strip()
    if not birth_date and len(id_num) >= 14 and id_num[6:14].isdigit():
        birth_date = f"{id_num[6:10]}-{id_num[10:12]}-{id_num[12:14]}"

    # 状态判断
    status = body.status.strip() or "正常"
    end_date = body.end_date.strip()
    if status == "正常" and end_date:
        today = datetime.now().strftime("%Y-%m-%d")
        if end_date < today:
            status = "失效"

    updates = {
        "name": name,
        "id_number": id_num,
        "id_type": body.id_type.strip() or "身份证",
        "birth_date": birth_date,
        "company": body.company.strip(),
        "start_date": body.start_date.strip(),
        "end_date": end_date,
        "job_title": body.job_title.strip(),
        "insurance_company": body.insurance_company.strip(),
        "policy_number": body.policy_number.strip(),
        "status": status,
    }

    if db.update_personnel(person_id, updates):
        return JSONResponse({"success": True, "message": "更新成功"})
    raise HTTPException(status_code=404, detail="记录不存在")


@app.delete("/api/personnel/{person_id}")
async def delete_personnel(person_id: int):
    """删除保单人员数据"""
    if db.delete_personnel(person_id):
        return JSONResponse({"success": True, "message": "删除成功"})
    raise HTTPException(status_code=404, detail="记录不存在")


@app.get("/api/personnel/export")
async def export_personnel():
    """下载保单人员数据为 Excel 表格"""
    persons = db.get_insurance_personnel()
    if not persons:
        raise HTTPException(status_code=404, detail="暂无保单人员数据")

    wb = Workbook()
    ws = wb.active
    ws.title = "保单人员数据"

    # 表头样式
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # 写表头
    for col_idx, (label, _) in enumerate(PERSONNEL_FIELDS, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 写数据
    data_font = Font(name="微软雅黑", size=10)
    for row_idx, p in enumerate(persons, 2):
        for col_idx, (_, key) in enumerate(PERSONNEL_FIELDS, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=p.get(key, "") or "")
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    # 列宽
    col_widths = {
        "姓名": 12, "证件号码": 24, "证件类型": 10, "出生日期": 14,
        "所属公司": 28, "批改类型": 10, "起始时间": 14, "起止时间": 14,
        "岗位名称": 16, "保险公司": 22, "保单号": 30, "来源文件": 40,
    }
    for col_idx, (label, _) in enumerate(PERSONNEL_FIELDS, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = col_widths.get(label, 15)

    ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"保单人员数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    encoded_filename = quote(filename)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


# ==================== 公司系统对接 ====================

# Excel 模板路径（项目根下的模板文件）
EXCEL_TEMPLATE_PATH = os.path.join(_BASE_DIR, "最新保险数据下载模板.xlsx")


@app.on_event("startup")
async def startup_event():
    """服务启动时启动会话续期 + 定时任务调度器"""
    _session_manager.start()

    # 飞书多维表格 webhook 推送器（启动时初始化单例，自动从 .feishu_webhook.json 读取配置）
    try:
        init_feishu_pusher()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        logger.warning("飞书 webhook pusher 初始化失败（不影响其他功能）: %s", e)

    # 任务1：每日打卡检查（同步打卡 → 覆盖对比 → 邮件/短信提醒）
    def daily_task():
        return run_daily_check(session_manager=_session_manager)

    # 任务2：到期提醒（查询还有 N 天到期的人员保险 → 发邮件提醒续保）
    def expiry_task():
        cfg = scheduler_mod.load_scheduler_config()
        ahead_days = cfg.get("expiry_ahead_days", 3)
        return run_expiry_check(ahead_days=ahead_days)

    # 任务3：未参保人员汇总（上午 09:00）→ 给保险管理人员汇总邮件
    def morning_summary_task():
        return run_uninsured_summary(session_manager=_session_manager, period="morning")

    # 任务4：未参保人员汇总（下午 16:30）→ 给保险管理人员再次汇总（含上午已发过的）
    def afternoon_summary_task():
        return run_uninsured_summary(session_manager=_session_manager, period="afternoon")

    # 任务5：打卡数据清理（每日 00:00 午夜）→ 删除昨日及更早的 punch_records
    def daily_cleanup_task():
        return run_daily_cleanup(days_to_keep=1)

    scheduler_mod.create_scheduler()
    scheduler_mod.get_scheduler().add_task("daily_check", daily_task, "sync_time")
    scheduler_mod.get_scheduler().add_task("expiry_reminder", expiry_task, "expiry_time")
    scheduler_mod.get_scheduler().add_task("morning_summary", morning_summary_task, "summary_morning_time")
    scheduler_mod.get_scheduler().add_task("afternoon_summary", afternoon_summary_task, "summary_afternoon_time")
    scheduler_mod.get_scheduler().add_task("daily_cleanup", daily_cleanup_task, "cleanup_time")
    scheduler_mod.get_scheduler().start()

    # 实时打卡事件消费者：ERP 每推送一条打卡，秒级核对保险并通知项目经理/保险管理人员
    try:
        start_realtime_consumer(session_manager=_session_manager)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        logger.warning("实时消费者启动失败（不影响其他功能）: %s", e)


@app.on_event("shutdown")
async def shutdown_event():
    """服务停止时清理会话和调度器"""
    _session_manager.stop()
    if scheduler_mod.get_scheduler():
        scheduler_mod.get_scheduler().stop()


@app.get("/api/session/status")
async def session_status():
    """检查公司系统会话状态"""
    return {
        "active": _session_manager.is_active(),
        "base_url": _session_manager._base_url,
    }


@app.post("/api/sync-excel")
async def sync_excel():
    """将最近一次提取的增减保结果同步到 Excel 模板

    - 减保人员: 从 Excel 中删除
    - 增保人员: 不存在则新增，已存在则跳过
    - 不改变 Excel 字段结构，只填有数据的字段
    """
    if not _latest_results:
        raise HTTPException(status_code=404, detail="无提取结果，请先上传保单文件")

    if not os.path.exists(EXCEL_TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail=f"Excel 模板不存在: {EXCEL_TEMPLATE_PATH}")

    try:
        stats = sync_excel_with_extraction(
            excel_path=EXCEL_TEMPLATE_PATH,
            extraction_results=_latest_results,
        )
        return JSONResponse({
            "success": True,
            "message": "同步完成",
            "stats": stats,
            "excel_path": EXCEL_TEMPLATE_PATH,
        })
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"同步失败: {e}")


@app.post("/api/upload-erp")
async def upload_to_erp():
    """已禁用：禁止登录系统上传数据到系统数据库"""
    raise HTTPException(status_code=403, detail="已取消上传 ERP 功能，禁止向系统数据库写入数据")


# ==================== 全链路 Pipeline ====================

@app.post("/api/pipeline")
async def run_pipeline():
    """已禁用：禁止登录系统上传数据到系统数据库

    原全链路流水线（上传保单→提取→同步Excel→上传ERP）已取消 ERP 上传环节。
    """
    raise HTTPException(status_code=403, detail="已取消上传 ERP 功能，禁止向系统数据库写入数据")


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    # 单实例端口锁：OS 级原子创建，确保全局只有一个 server 能绑定 8765。
    # 多 watchdog（venv/uv）可能同时拉起多个 server 进程，抢不到锁的立即退出，
    # 避免「地址已被占用」崩溃循环；持有锁的 server 常驻服务。
    _PORT_LOCK = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        ".server.port.lock",
    )
    try:
        _port_lock_fd = _os.open(
            _PORT_LOCK, _os.O_CREAT | _os.O_EXCL | _os.O_RDWR
        )
        _os.write(_port_lock_fd, str(_os.getpid()).encode("utf-8"))
    except FileExistsError:
        # 锁已存在：检查持有者是否真的"是"我们的 python server。
        # 必须同时满足：①OpenProcess 拿到句柄 ②QueryFullProcessImageNameW 是 python.exe/pythonw.exe。
        # 否则视为死锁或 PID 复用（被别的进程接管了），清理后重试。
        _lock_is_valid = False
        try:
            _old = int(open(_PORT_LOCK, "r", encoding="utf-8").read().strip())
            import ctypes as _ctypes
            _h = _ctypes.windll.kernel32.OpenProcess(0x1000, False, _old)
            if _h:
                try:
                    _img_buf = _ctypes.create_unicode_buffer(512)
                    _img_sz = _ctypes.c_uint(_ctypes.sizeof(_img_buf))
                    if _ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        _h, 0, _img_buf, _ctypes.byref(_img_sz)
                    ):
                        _img = _img_buf.value.lower()
                        if _img.endswith("\\python.exe") or _img.endswith("\\pythonw.exe"):
                            _lock_is_valid = True
                finally:
                    _ctypes.windll.kernel32.CloseHandle(_h)
            if _lock_is_valid:
                print(f"[port-lock] 8765 已被 PID {_old} (python) 占用，本 server 退出。")
                _sys.exit(0)
            print(f"[port-lock] 锁指向 PID {_old} 但它不是 python 进程（PID 已死或被复用），清理锁后重试...")
        except Exception as e:
            print(f"[port-lock] 锁检查异常 {e}，清理锁后重试...")
        try:
            _os.remove(_PORT_LOCK)
            _port_lock_fd = _os.open(
                _PORT_LOCK, _os.O_CREAT | _os.O_EXCL | _os.O_RDWR
            )
            _os.write(_port_lock_fd, str(_os.getpid()).encode("utf-8"))
        except Exception:
            print("[port-lock] 端口锁获取失败，本 server 退出。")
            _sys.exit(0)

    import uvicorn
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",  # bind all interfaces: allow LAN access (was 127.0.0.1)
            port=8765,
            workers=1,
        )
    finally:
        try:
            _os.close(_port_lock_fd)
        except Exception:
            pass
        try:
            if _os.path.exists(_PORT_LOCK):
                _os.remove(_PORT_LOCK)
        except Exception:
            pass
