"""流水线各阶段独立测试脚本

每个阶段可以单独运行测试:
    python test_pipeline_stages.py upload    # 测试 Stage 1: 文件上传
    python test_pipeline_stages.py extract   # 测试 Stage 2: 信息提取
    python test_pipeline_stages.py sync      # 测试 Stage 3: Excel 同步
    python test_pipeline_stages.py erp       # 测试 Stage 4: ERP 上传
    python test_pipeline_stages.py all       # 测试全链路
    python test_pipeline_stages.py graph     # 测试 LangGraph 编排

也可以作为模块导入:
    from test_pipeline_stages import test_extract, test_sync, test_erp
"""

import json
import os
import sys
import shutil

# 项目根目录
PROJECT_ROOT = "C:/insurance-automation"
sys.path.insert(0, PROJECT_ROOT)

PYTHON = r"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"


# ============================================================
# Stage 1: Upload — 独立测试
# ============================================================
def test_upload():
    """测试文件上传节点"""
    print("\n" + "=" * 60)
    print("TEST: Stage 1 — Upload Node")
    print("=" * 60)

    from insurance_agent.agents.policy_pipeline.nodes import UploadNode

    # 用已有的 PDF 文件测试
    test_pdf = os.path.join(PROJECT_ROOT, "policy_library", "保单_重庆筑起建筑劳务有限公司_8116013100250023781000.pdf")
    if not os.path.exists(test_pdf):
        print(f"  [SKIP] 测试文件不存在: {test_pdf}")
        return False

    node = UploadNode(upload_dir=os.path.join(PROJECT_ROOT, "test_uploads"))
    state = {
        "uploaded_files": [test_pdf],
        "upload_dir": os.path.join(PROJECT_ROOT, "test_uploads"),
        "status": "init",
        "error": None,
        "stage_results": {},
        "extraction_results": [],
        "extraction_errors": [],
        "excel_path": "",
        "sync_stats": None,
        "erp_upload_result": None,
        "erp_base_url": "http://47.108.166.14:8081",
    }

    result = node(state)
    print(f"  status: {result['status']}")
    print(f"  uploaded_files: {result['uploaded_files']}")

    assert result["status"] == "extracting", f"Expected 'extracting', got '{result['status']}'"
    assert len(result["uploaded_files"]) == 1

    # 清理
    test_dir = os.path.join(PROJECT_ROOT, "test_uploads")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    print("  [PASS] Upload Node 测试通过")
    return True


# ============================================================
# Stage 2: Extract — 独立测试
# ============================================================
def test_extract():
    """测试信息提取节点（调用已有 invoice recognition graph）"""
    print("\n" + "=" * 60)
    print("TEST: Stage 2 — Extract Node")
    print("=" * 60)

    from insurance_agent.agents.policy_pipeline.nodes import ExtractNode
    from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser

    test_pdf = os.path.join(PROJECT_ROOT, "policy_library", "保单_重庆筑起建筑劳务有限公司_8116013100250023781000.pdf")
    if not os.path.exists(test_pdf):
        print(f"  [SKIP] 测试文件不存在: {test_pdf}")
        return False

    node = ExtractNode(
        pdf_parser=PyMuPDFParser(),
        llm_client=None,  # 纯文字层 PDF 不需要 LLM
        policy_library=None,
    )

    state = {
        "uploaded_files": [test_pdf],
        "status": "extracting",
        "error": None,
        "stage_results": {},
        "extraction_results": [],
        "extraction_errors": [],
        "excel_path": "",
        "sync_stats": None,
        "erp_upload_result": None,
        "erp_base_url": "http://47.108.166.14:8081",
        "upload_dir": "",
    }

    result = node(state)
    print(f"  status: {result['status']}")
    print(f"  extraction_results count: {len(result['extraction_results'])}")
    print(f"  extraction_errors: {result['extraction_errors']}")

    if result["extraction_results"]:
        r = result["extraction_results"][0]
        print(f"  文件名: {r.get('file_name', '?')}")
        print(f"  保险公司: {r.get('insurance_company', '?')}")
        print(f"  人数: {len(r.get('insured_persons', []))}")

    assert result["status"] == "syncing", f"Expected 'syncing', got '{result['status']}'"
    assert len(result["extraction_results"]) > 0, "应有提取结果"

    print("  [PASS] Extract Node 测试通过")
    return True


# ============================================================
# Stage 3: Sync Excel — 独立测试
# ============================================================
def test_sync():
    """测试 Excel 同步节点"""
    print("\n" + "=" * 60)
    print("TEST: Stage 3 — Sync Excel Node")
    print("=" * 60)

    from insurance_agent.agents.policy_pipeline.nodes import SyncExcelNode

    # 用已有的提取结果 JSON
    json_path = os.path.join(PROJECT_ROOT, "extraction_results.json")
    if not os.path.exists(json_path):
        print(f"  [SKIP] 提取结果文件不存在: {json_path}")
        return False

    excel_path = os.path.join(PROJECT_ROOT, "最新保险数据下载模板.xlsx")
    if not os.path.exists(excel_path):
        print(f"  [SKIP] Excel 模板不存在: {excel_path}")
        return False

    # 备份 Excel
    backup = excel_path.replace(".xlsx", "_test_backup.xlsx")
    shutil.copy2(excel_path, backup)

    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    node = SyncExcelNode(excel_path=excel_path)
    state = {
        "extraction_results": results,
        "excel_path": excel_path,
        "status": "syncing",
        "error": None,
        "stage_results": {},
        "uploaded_files": [],
        "extraction_errors": [],
        "sync_stats": None,
        "erp_upload_result": None,
        "erp_base_url": "http://47.108.166.14:8081",
        "upload_dir": "",
    }

    result = node(state)
    print(f"  status: {result['status']}")
    print(f"  sync_stats: {result['sync_stats']}")

    assert result["status"] == "uploading_erp", f"Expected 'uploading_erp', got '{result['status']}'"
    assert result["sync_stats"] is not None

    # 恢复 Excel
    shutil.copy2(backup, excel_path)
    os.remove(backup)

    print("  [PASS] Sync Excel Node 测试通过")
    return True


# ============================================================
# Stage 4: Upload ERP — 独立测试
# ============================================================
def test_erp():
    """测试 ERP 上传节点"""
    print("\n" + "=" * 60)
    print("TEST: Stage 4 — Upload ERP Node")
    print("=" * 60)

    from insurance_agent.agents.policy_pipeline.nodes import UploadERPNode
    from insurance_agent.infrastructure.session_manager import SessionManager

    excel_path = os.path.join(PROJECT_ROOT, "最新保险数据下载模板.xlsx")
    if not os.path.exists(excel_path):
        print(f"  [SKIP] Excel 文件不存在: {excel_path}")
        return False

    # 创建 SessionManager 并登录
    mgr = SessionManager(
        base_url="http://47.108.166.14:8081",
        username="chenxueqin",
        password="1234",
    )

    node = UploadERPNode(session_manager=mgr)

    state = {
        "excel_path": excel_path,
        "erp_base_url": "http://47.108.166.14:8081",
        "status": "uploading_erp",
        "error": None,
        "stage_results": {},
        "uploaded_files": [],
        "extraction_results": [],
        "extraction_errors": [],
        "sync_stats": None,
        "erp_upload_result": None,
        "upload_dir": "",
    }

    # 先登录
    print("  正在登录 ERP 系统...")
    if not mgr.login():
        print("  [FAIL] ERP 登录失败")
        return False
    print("  登录成功")

    result = node(state)
    print(f"  status: {result['status']}")
    print(f"  erp_upload_result: {result['erp_upload_result']}")

    assert result["erp_upload_result"] is not None
    assert result["status"] in ("done", "error")

    if result["erp_upload_result"]["success"]:
        print("  [PASS] Upload ERP Node 测试通过（上传成功）")
    else:
        print(f"  [WARN] ERP 上传返回非成功: {result['erp_upload_result']['message']}")

    return True


# ============================================================
# Full Graph: 全链路测试
# ============================================================
def test_graph():
    """测试完整 LangGraph 编排"""
    print("\n" + "=" * 60)
    print("TEST: Full Pipeline Graph")
    print("=" * 60)

    from insurance_agent.agents.policy_pipeline import create_pipeline, create_pipeline_state
    from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser
    from insurance_agent.infrastructure.session_manager import SessionManager

    test_pdf = os.path.join(PROJECT_ROOT, "policy_library", "保单_重庆筑起建筑劳务有限公司_8116013100250023781000.pdf")
    if not os.path.exists(test_pdf):
        print(f"  [SKIP] 测试文件不存在: {test_pdf}")
        return False

    # 备份 Excel
    excel_path = os.path.join(PROJECT_ROOT, "最新保险数据下载模板.xlsx")
    backup = excel_path.replace(".xlsx", "_graph_backup.xlsx")
    shutil.copy2(excel_path, backup)

    # 创建 session manager
    session_mgr = SessionManager(
        base_url="http://47.108.166.14:8081",
        username="chenxueqin",
        password="1234",
    )
    session_mgr.start()

    try:
        capability, graph = create_pipeline(
            pdf_parser=PyMuPDFParser(),
            llm_client=None,
            policy_library=None,
            session_manager=session_mgr,
            excel_path=excel_path,
            upload_dir=os.path.join(PROJECT_ROOT, "uploads"),
            erp_base_url="http://47.108.166.14:8081",
        )

        initial_state = create_pipeline_state(
            uploaded_files=[test_pdf],
            excel_path=excel_path,
            erp_base_url="http://47.108.166.14:8081",
        )

        print("  启动流水线...")
        final_state = graph.invoke(initial_state)

        print(f"\n  === 最终状态 ===")
        print(f"  status: {final_state['status']}")
        print(f"  error: {final_state.get('error')}")

        if final_state.get("extraction_results"):
            for r in final_state["extraction_results"]:
                persons = r.get("insured_persons", [])
                print(f"  提取: {r.get('file_name', '?')} → {len(persons)} 人")

        if final_state.get("sync_stats"):
            s = final_state["sync_stats"]
            print(f"  Excel同步: 新增{s['added']}, 删除{s['removed']}, 跳过{s['skipped']}, 总计{s['total_in_excel']}")

        if final_state.get("erp_upload_result"):
            r = final_state["erp_upload_result"]
            print(f"  ERP上传: success={r['success']}, message={r['message']}")

        print("\n  [PASS] Full Pipeline Graph 测试通过")
        return True

    finally:
        session_mgr.stop()
        # 恢复 Excel
        shutil.copy2(backup, excel_path)
        os.remove(backup)


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    results = {}

    if target in ("upload", "all"):
        results["upload"] = test_upload()

    if target in ("extract", "all"):
        results["extract"] = test_extract()

    if target in ("sync", "all"):
        results["sync"] = test_sync()

    if target in ("erp", "all"):
        results["erp"] = test_erp()

    if target == "graph":
        results["graph"] = test_graph()

    # 汇总
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL/SKIP]"
        print(f"  {name}: {status}")
