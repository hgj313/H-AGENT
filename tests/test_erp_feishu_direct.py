"""ERP → 飞书多维表格 直连链路单元测试

覆盖纯函数与幂等存储，不发网络请求、不连 MQ。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_feishu_direct.mapper import (  # noqa: E402
    build_fields,
    extract_punch_date,
    normalize_events,
    to_millis,
    to_number,
)
from erp_feishu_direct.store import SyncMapStore  # noqa: E402


# ==================== 时间转换 ====================

def test_to_millis_datetime_string():
    ms = to_millis("2026-11-10 08:32:00")
    assert isinstance(ms, int) and ms > 1_700_000_000_000


def test_to_millis_iso8601():
    ms = to_millis("2026-08-21T08:32:00")
    assert isinstance(ms, int) and ms > 1_700_000_000_000


def test_to_millis_date_only():
    assert to_millis("2026-11-10") is not None


def test_to_millis_numeric_10digit():
    assert to_millis(1762700000) == 1762700000000


def test_to_millis_numeric_13digit_passthrough():
    assert to_millis(1762700000000) == 1762700000000


def test_to_millis_invalid():
    assert to_millis("不是时间") is None
    assert to_millis("") is None
    assert to_millis(None) is None
    assert to_millis(True) is None


def test_to_number():
    assert to_number("45") == 45
    assert to_number(45) == 45
    assert to_number("") is None
    assert to_number("abc") is None
    assert to_number(True) is None


# ==================== 打卡日期提取 ====================

def test_extract_punch_date_from_punch_date_field():
    ev = {"punchDate": "2026-11-10", "punchTime": "2026-11-10 08:00:00"}
    assert extract_punch_date(ev) == "2026-11-10"


def test_extract_punch_date_from_punch_time():
    """ERP 消息常只带 punchTime"""
    ev = {"punchTime": "2026-11-10T08:32:00"}
    assert extract_punch_date(ev) == "2026-11-10"


def test_extract_punch_date_slash_format():
    ev = {"punchTime": "2026/11/10 08:32:00"}
    assert extract_punch_date(ev) == "2026-11-10"


# ==================== 字段映射 ====================

def test_build_fields_full_event():
    ev = {
        "memberName": "莫凤花",
        "identificationNumber": "452428196708182024",
        "projectName": "佛山保利天瓒西项目",
        "teamName": "莫正彬-班组",
        "supplierName": "深圳春羽园林工程有限公司",
        "categoryName": "软景劳务",
        "projectManager": "陈科",
        "managerPhone": "18108301896",
        "managerEmail": "290033673@qq.com",
        "punchDate": "2026-11-10",
        "punchTime": "2026-11-10 00:04:15",
    }
    f = build_fields(ev)
    assert f["姓名"] == "莫凤花"
    assert f["身份证号"] == "452428196708182024"
    assert f["项目名称"] == "佛山保利天瓒西项目"
    assert f["劳务公司"] == "深圳春羽园林工程有限公司"
    assert f["项目经理"] == "陈科"
    assert isinstance(f["打卡日期"], int)
    assert isinstance(f["打卡时间"], int)


def test_build_fields_skips_empty():
    ev = {"memberName": "张三", "teamName": "", "punchTime": "2026-11-10 08:00:00"}
    f = build_fields(ev)
    assert f["姓名"] == "张三"
    assert "班组" not in f
    assert "身份证号" not in f


def test_build_fields_custom_mapping():
    ev = {"memberName": "张三", "projectName": "P1"}
    f = build_fields(ev, {"姓名": "memberName"})
    assert f == {"姓名": "张三"}


# ==================== 消息解析 ====================

def test_normalize_events_plain_array():
    raw = json.dumps([{"memberName": "A", "identificationNumber": "1"}])
    evs = normalize_events(raw)
    assert len(evs) == 1 and evs[0]["memberName"] == "A"


def test_normalize_events_wrapped_events_key():
    raw = json.dumps({"events": [{"memberName": "A"}, {"memberName": "B"}]})
    evs = normalize_events(raw)
    assert len(evs) == 2


def test_normalize_events_single_object():
    raw = json.dumps({"memberName": "A"})
    evs = normalize_events(raw)
    assert len(evs) == 1


def test_normalize_events_double_encoded_json():
    """Java/Kotlin 会把整个 JSON 再包一层引号"""
    inner = json.dumps({"memberName": "A", "identificationNumber": "1"})
    raw = json.dumps(inner)
    evs = normalize_events(raw)
    assert len(evs) == 1 and evs[0]["memberName"] == "A"


def test_normalize_events_applies_rename():
    raw = json.dumps({"employeeName": "张三", "idCard": "110101199001011234"})
    evs = normalize_events(raw, {"employeeName": "memberName", "idCard": "identificationNumber"})
    assert evs[0]["memberName"] == "张三"
    assert evs[0]["identificationNumber"] == "110101199001011234"


def test_normalize_events_invalid_returns_empty():
    assert normalize_events("这不是JSON") == []
    assert normalize_events(None) == []
    assert normalize_events("") == []


# ==================== 幂等映射存储 ====================

def test_store_set_and_get():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        s = SyncMapStore(p)
        assert s.get_record_id("2026-11-10", "111") is None
        s.set_record_id("2026-11-10", "111", "recAAA")
        assert s.get_record_id("2026-11-10", "111") == "recAAA"


def test_store_persists_across_instances():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        SyncMapStore(p).set_record_id("2026-11-10", "111", "recAAA")
        s2 = SyncMapStore(p)
        assert s2.get_record_id("2026-11-10", "111") == "recAAA"


def test_store_set_many():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        s = SyncMapStore(p)
        s.set_many("2026-11-10", {"1": "r1", "2": "r2"})
        assert s.get_record_id("2026-11-10", "1") == "r1"
        assert s.get_record_id("2026-11-10", "2") == "r2"
        assert len(s.get_day_map("2026-11-10")) == 2


def test_store_dates_isolated():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        s = SyncMapStore(p)
        s.set_record_id("2026-11-10", "111", "recA")
        s.set_record_id("2026-11-11", "111", "recB")
        assert s.get_record_id("2026-11-10", "111") == "recA"
        assert s.get_record_id("2026-11-11", "111") == "recB"


def test_store_cleanup_expired():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        s = SyncMapStore(p, keep_days=1)
        s.set_record_id("2020-01-01", "111", "recOld")
        s.set_record_id("2099-01-01", "222", "recNew")
        # 触发清理
        s.set_record_id("2099-01-01", "333", "recNew2")
        assert s.get_record_id("2020-01-01", "111") is None
        assert s.get_record_id("2099-01-01", "222") == "recNew"


def test_store_file_is_valid_json():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "map.json")
        s = SyncMapStore(p)
        s.set_record_id("2026-11-10", "111", "recAAA")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["2026-11-10"]["111"] == "recAAA"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all tests passed")
