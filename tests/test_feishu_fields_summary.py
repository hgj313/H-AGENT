"""回归测试：飞书推送日志的字段摘要（_format_fields_summary）

背景
----
排查「飞书表格缺项目等字段」时发现：推送成功日志只打印 name + punch_time，
其余 9 个字段是否真的发出去了**完全不可见**，导致无法区分
「本地没给」/「飞书没落」/「字段名对不上」三种根因。

本次新增 `_format_fields_summary`：
  1) 把实际发送的全部字段摊开打印
  2) 显式标出空字段
  3) 保持 payload 本身零改动（不污染调用方对象）

同时锁定一条重要不变量：**日志改动不得影响发送字节**。
"""

import importlib.util
import json
import os
import sys

PUSHER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "insurance_agent", "tools", "feishu_webhook_pusher.py",
)
spec_obj = importlib.util.spec_from_file_location("feishu_webhook_pusher_sum", PUSHER_PATH)
mod = importlib.util.module_from_spec(spec_obj)
spec_obj.loader.exec_module(mod)

_format_fields_summary = mod._format_fields_summary


def test_summary_lists_all_filled_fields():
    """所有有值的字段都要出现在摘要里。"""
    payload = {
        "name": "张三",
        "id_number": "110101199001011234",
        "project_name": "重庆观宸二期",
        "team_name": "魏昭木-班组",
        "supplier_name": "铭鑫玻璃厂",
        "category_name": "玻璃安装",
        "project_manager": "尹祥",
        "manager_phone": "19112021333",
        "manager_email": "yin@example.com",
        "punch_time": "2026/09/04 06:54",
        "punch_date": "2026-09-04",
    }
    s = _format_fields_summary(payload)
    for token in ("张三", "110101199001011234", "重庆观宸二期", "魏昭木-班组",
                  "铭鑫玻璃厂", "玻璃安装", "尹祥", "19112021333", "yin@example.com"):
        assert token in s, f"摘要缺少字段值 {token}: {s}"
    assert "空字段" not in s, f"不该有空字段标记: {s}"
    print("✅ 全部字段值都出现在摘要中")


def test_summary_marks_empty_fields():
    """空字段必须被显式标出（这正是排查缺列的关键信号）。"""
    payload = {
        "name": "李四",
        "id_number": "510101199001011234",
        "project_name": "",
        "team_name": None,
        "supplier_name": "   ",
        "punch_time": "2026/09/04 06:54",
    }
    s = _format_fields_summary(payload)
    assert "空字段" in s, f"应标出空字段: {s}"
    for label in ("项目", "班组", "劳务公司"):
        assert label in s.split("空字段:")[1], f"空字段列表缺少 {label}: {s}"
    # 有值的字段不能被误标为空
    assert "李四" in s
    print("✅ 空字段被正确标出")


def test_summary_handles_extra_fields():
    """白名单外的额外字段（如 source）也要显示，不能静默丢弃。"""
    payload = {"name": "王五", "source": "realtime"}
    s = _format_fields_summary(payload)
    assert "source=realtime" in s, f"额外字段未显示: {s}"
    print("✅ 额外字段被显示")


def test_summary_truncates_long_values():
    """超长值要截断，避免日志爆行。"""
    payload = {"name": "A" * 200, "project_name": "B" * 200}
    s = _format_fields_summary(payload, max_len=24)
    assert "A" * 24 in s
    assert "A" * 25 not in s, "超长值未截断"
    print("✅ 超长值被截断")


def test_summary_handles_non_dict():
    """非 dict 输入不应抛异常。"""
    assert _format_fields_summary(None) == ""
    assert _format_fields_summary("string") == ""
    print("✅ 非 dict 输入安全")


def test_summary_does_not_mutate_payload():
    """摘要函数必须是只读的——不能污染调用方对象。"""
    payload = {"name": "赵六", "project_name": "某项目"}
    snapshot = dict(payload)
    _format_fields_summary(payload)
    assert payload == snapshot, "摘要函数修改了原 payload"
    print("✅ payload 未被修改")


def test_send_bytes_unchanged_by_logging():
    """核心不变量：新增日志不得改变发送字节（字段一个都不能少、不能多）。"""
    import tempfile
    import requests as _real_requests

    tmpdir = tempfile.mkdtemp()
    cfg_file = os.path.join(tmpdir, "config.json")
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump({
            "enabled": True,
            "webhook_url": "http://127.0.0.1:1/dummy",
            "bearer_token": "dummy",
            "timeout": 1,
            "max_retries": 1,
        }, f)

    # ⚠️ 必须先替换 requests.post 再构造 pusher，
    #    否则 worker 线程起来时用的是真实 requests（既有集成测试同此坑）。
    captured = {}
    orig_post = _real_requests.post

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        captured["data"] = data
        captured["headers"] = headers

        class R:
            status_code = 200
            text = '{"code":0,"msg":"ok"}'

            @staticmethod
            def json():
                return {"code": 0, "msg": "ok"}

        return R()

    _real_requests.post = fake_post
    try:
        pusher = mod.FeishuWebhookPusher(config_path=cfg_file)

        full_payload = {
            "name": "张三",
            "id_number": "110101199001011234",
            "project_name": "重庆观宸二期",
            "team_name": "魏昭木-班组",
            "supplier_name": "铭鑫玻璃厂",
            "category_name": "玻璃安装",
            "project_manager": "尹祥",
            "manager_phone": "19112021333",
            "manager_email": "yin@example.com",
            "punch_time": "2026-09-04 06:54:53",
            "punch_date": "2026-09-04",
        }
        expected = dict(full_payload)
        expected["punch_time"] = "2026/09/04 06:54"

        pusher.push(full_payload, source="test")
        import time
        time.sleep(1.5)
        pusher.stop(timeout=2)
    finally:
        _real_requests.post = orig_post

    assert "data" in captured, "未捕获到发送请求（mock 未生效）"
    sent = json.loads(captured["data"].decode("utf-8"))
    assert sent == expected, (
        f"发送字节与预期不符\n实际: {sent}\n预期: {expected}"
    )
    # 原 payload 未被污染
    assert full_payload["punch_time"] == "2026-09-04 06:54:53"
    print("✅ 发送字节逐字段一致，日志改动零副作用")


if __name__ == "__main__":
    tests = [
        test_summary_lists_all_filled_fields,
        test_summary_marks_empty_fields,
        test_summary_handles_extra_fields,
        test_summary_truncates_long_values,
        test_summary_handles_non_dict,
        test_summary_does_not_mutate_payload,
        test_send_bytes_unchanged_by_logging,
    ]
    for t in tests:
        t()
    print(f"\n全部通过：{len(tests)} 项")
