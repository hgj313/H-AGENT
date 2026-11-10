"""打卡数据 → 飞书多维表格 同步器单元测试

只测纯函数与字段映射（不发网络请求）。
需要凭证的端到端验证走 `POST /api/feishu-bitable/probe`。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insurance_agent.tools.punch_bitable_sync import (  # noqa: E402
    DEFAULT_FIELD_MAPPING,
    build_fields,
    to_millis,
    to_number,
)


def test_to_millis_from_datetime_string():
    """标准日期时间串 → 毫秒时间戳"""
    ms = to_millis("2026-11-10 00:04:15")
    assert isinstance(ms, int)
    assert ms > 1_700_000_000_000


def test_to_millis_from_date_only():
    """纯日期（打卡日期列）→ 当天 00:00 的毫秒时间戳"""
    ms = to_millis("2026-11-10")
    assert isinstance(ms, int)
    assert ms > 1_700_000_000_000


def test_to_millis_from_slash_format():
    """斜杠格式（ERP 原始返回常见）"""
    assert to_millis("2026/11/10 00:04:15") is not None


def test_to_millis_from_numeric_timestamp():
    """10 位秒 → 13 位毫秒"""
    ms = to_millis("1762700000")
    assert ms == 1762700000000


def test_to_millis_passthrough_13digit():
    """已是 13 位毫秒 → 原样返回"""
    assert to_millis(1762700000000) == 1762700000000


def test_to_millis_invalid_returns_none():
    """无法解析 → None（不写脏值进飞书）"""
    assert to_millis("不是时间") is None
    assert to_millis("") is None
    assert to_millis(None) is None


def test_to_number():
    """数字列转换"""
    assert to_number("45") == 45
    assert to_number(45) == 45
    assert to_number("") is None
    assert to_number("abc") is None
    # 布尔不能当数字传飞书
    assert to_number(True) is None


def test_build_fields_converts_dates_and_numbers():
    """字段映射：日期转毫秒、年龄转数字、文本保持字符串"""
    rec = {
        "member_name": "莫凤花",
        "identification_number": "452428196708182024",
        "project_name": "佛山保利天瓒西项目",
        "age": "45",
        "punch_date": "2026-11-10",
        "punch_time": "2026-11-10 00:04:15",
    }
    fields = build_fields(rec, DEFAULT_FIELD_MAPPING)

    assert fields["姓名"] == "莫凤花"
    assert fields["身份证号"] == "452428196708182024"
    assert isinstance(fields["打卡日期"], int)
    assert isinstance(fields["打卡时间"], int)
    assert fields["年龄"] == 45


def test_build_fields_skips_empty_values():
    """空值字段不写入（避免污染飞书列）"""
    rec = {"member_name": "张三", "age": "", "punch_date": "2026-11-10"}
    fields = build_fields(rec, DEFAULT_FIELD_MAPPING)

    assert fields["姓名"] == "张三"
    assert "年龄" not in fields
    assert "身份证号" not in fields


def test_build_fields_respects_custom_mapping():
    """自定义映射只写声明的列"""
    rec = {"member_name": "张三", "project_name": "P1"}
    fields = build_fields(rec, {"姓名": "member_name"})

    assert fields == {"姓名": "张三"}


def test_build_fields_skips_record_without_id():
    """无身份证号的记录应被上层跳过（此处确认映射层不产生脏行）"""
    rec = {"member_name": "无证件", "punch_date": "2026-11-10"}
    fields = build_fields(rec, DEFAULT_FIELD_MAPPING)
    assert "身份证号" not in fields


if __name__ == "__main__":
    # 脚本式运行：pytest 环境用 pytest 跑，此处仅做冒烟验证
    test_to_millis_from_datetime_string()
    test_to_millis_from_date_only()
    test_to_millis_from_slash_format()
    test_to_millis_from_numeric_timestamp()
    test_to_millis_passthrough_13digit()
    test_to_millis_invalid_returns_none()
    test_to_number()
    test_build_fields_converts_dates_and_numbers()
    test_build_fields_skips_empty_values()
    test_build_fields_respects_custom_mapping()
    test_build_fields_skips_record_without_id()
    print("all tests passed")
