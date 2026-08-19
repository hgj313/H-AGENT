"""保险单识别 Web 服务

提供前端界面上传 PDF 附件，提取被保人员信息，输出表格文件。
基于现有 insurance_agent 智能体，不修改 Agent 行为，仅做 Web 封装。
"""

import csv
import io
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from pydantic import BaseModel

# 确保项目根目录在 path 中（本文件位于 web_app/ 下，上级即项目根）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)

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
from insurance_agent.agents.policy_pipeline import create_pipeline, create_pipeline_state

app = FastAPI(title="保险单识别系统", version="1.0.0")

# 静态文件
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# 全局状态
_llm_client = None
_policy_library = PolicyLibrary()  # 默认用项目根下的 policy_library 目录
_latest_results: list[dict] = []  # 最近一次提取结果
_graph_cache = None  # 单例 graph，复用避免每次重建

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


def get_invoice_graph():
    """获取单例 invoice recognition graph（避免每次请求重建）"""
    global _graph_cache
    if _graph_cache is None:
        llm = get_llm()
        capability = InvoiceRecognitionCapability(
            pdf_parser=PyMuPDFParser(),
            llm_client=llm,
            policy_library=_policy_library,
        )
        _graph_cache = build_invoice_recognition_graph(capability)
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

    today = datetime.now().strftime("%Y-%m-%d")

    add_rows = []      # 增保人员（新增或更新）
    remove_ids = []    # 减保人员（状态改失效）

    for p in persons:
        mod_type = p.get("modification_type", "增保")
        id_num = (p.get("id_number") or "").strip()

        if mod_type == "减保":
            # 减保：按身份证号标记为失效
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

    # 减保：状态改失效
    if remove_ids:
        db.deactivate_insurance(remove_ids)


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


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """上传多个 PDF 文件并提取被保人员信息"""
    global _latest_results

    if not files:
        raise HTTPException(status_code=400, detail="未上传文件")

    saved_paths = []
    tmp_dir = tempfile.mkdtemp(prefix="insurance_upload_")

    for f in files:
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
    """获取保单文件库状态"""
    records = []
    for r in _policy_library.records:
        records.append({
            "file_name": r.file_name,
            "policy_type": r.policy_type,
            "policy_number": r.policy_number,
            "company": r.company,
            "insurance_company": r.insurance_company,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "persons_count": r.persons_count,
        })
    return {"records": records, "total": len(records)}


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
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")
    records = db.get_punch_records(punch_date, limit=10000)
    return JSONResponse({
        "success": True,
        "punch_date": punch_date,
        "total": len(records),
        "records": records,
    })


@app.post("/api/punch/sync")
async def sync_punch():
    """手动同步今日打卡数据"""
    # 打卡同步功能开关：关闭后禁止从 ERP 拉取打卡数据
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
    """检查打卡人员保险覆盖情况"""
    punch_date = datetime.now().strftime("%Y-%m-%d")
    try:
        result = coverage_check.check_insurance_coverage(punch_date)
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"检查失败: {e}")


@app.get("/api/punch/export-uninsured")
async def export_uninsured():
    """导出无正常保单人员清单为 Excel"""
    punch_date = datetime.now().strftime("%Y-%m-%d")
    result = coverage_check.check_insurance_coverage(punch_date)
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
async def daily_check(skip_sync: bool = False, force: bool = False, projects_limit: int = None, project_filter: str = None):
    """手动执行每日检查（同步打卡 → 覆盖对比 → 邮件提醒）

    skip_sync=true 时不重新同步打卡数据，直接使用数据库现有记录（便于用测试联系人触发验证）。
    force=true 时跳过「今日已发送过则跳过」的保护，强制重发（用于测试）。
    projects_limit=N 时只处理前 N 个项目（短信和邮件都只涉及这些项目），用于测试单条短信/单封邮件的发送。
    project_filter=项目名 时只处理该项目的人员（支持精确匹配与子串匹配），与 projects_limit 互斥。
    """
    try:
        sm = None if skip_sync else _session_manager
        result = run_daily_check(session_manager=sm, force=force, projects_limit=projects_limit, project_filter=project_filter)
        return JSONResponse(result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"每日检查失败: {e}")


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
    # 先刷新到期状态：已到起止日期的自动标记为失效
    db.refresh_expired_status()
    persons = db.get_insurance_personnel()
    rows = [_personnel_to_row(p) for p in persons]
    return JSONResponse({
        "success": True,
        "total": len(rows),
        "records": rows,
    })


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
        # 状态：未指定时根据起止日期判断
        status = _get("状态")
        if not status:
            end_date = _get("起止时间")
            today = datetime.now().strftime("%Y-%m-%d")
            status = "失效" if (end_date and end_date < today) else "正常"
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

    # 任务1：每日打卡检查（同步打卡 → 覆盖对比 → 邮件/短信提醒）
    def daily_task():
        return run_daily_check(session_manager=_session_manager)

    # 任务2：到期提醒（查询还有 N 天到期的人员保险 → 发邮件提醒续保）
    def expiry_task():
        cfg = scheduler_mod.load_scheduler_config()
        ahead_days = cfg.get("expiry_ahead_days", 3)
        return run_expiry_check(ahead_days=ahead_days)

    scheduler_mod.create_scheduler()
    scheduler_mod.get_scheduler().add_task("daily_check", daily_task, "sync_time")
    scheduler_mod.get_scheduler().add_task("expiry_reminder", expiry_task, "expiry_time")
    scheduler_mod.get_scheduler().start()


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
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8765,
        workers=1,
    )
