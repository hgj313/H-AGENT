"""直连链路端到端验证：用假飞书客户端跑完整的「MQ事件 → 飞书写入 → 幂等」闭环

不发网络请求、不连 MQ，验证业务逻辑正确性。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_feishu_direct.mapper import normalize_events  # noqa: E402
from erp_feishu_direct.store import SyncMapStore  # noqa: E402
from erp_feishu_direct.writer import FeishuWriter  # noqa: E402


class FakeFeishuClient:
    """模拟飞书 Bitable 客户端"""

    def __init__(self):
        self.records = {}          # record_id -> fields
        self._seq = 0
        self.create_calls = 0
        self.update_calls = 0

    def batch_create(self, chunk, table_id="", client_token=""):
        self.create_calls += 1
        out = []
        for item in chunk:
            self._seq += 1
            rid = f"rec{self._seq:04d}"
            self.records[rid] = dict(item.get("fields", {}))
            out.append({"record_id": rid, "fields": item.get("fields", {})})
        return out

    def batch_update(self, chunk, table_id="", client_token=""):
        self.update_calls += 1
        out = []
        for item in chunk:
            rid = item["record_id"]
            self.records[rid] = dict(item.get("fields", {}))
            out.append({"record_id": rid, "fields": item.get("fields", {})})
        return out


def _event(name, idn, time_str="2026-11-10 08:00:00"):
    return {
        "memberName": name,
        "identificationNumber": idn,
        "projectName": "佛山保利天瓒西项目",
        "teamName": "一班",
        "supplierName": "深圳春羽园林",
        "categoryName": "软景劳务",
        "punchTime": time_str,
    }


def test_e2e_first_write_creates_then_repeat_updates():
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        events = [_event("张三", "110101199001011234"), _event("李四", "110101199002022345")]

        # 第一次：全新 → 全部新增
        r1 = writer.write_batch(events)
        assert r1["created"] == 2, f"预期新增 2，实际 {r1}"
        assert r1["updated"] == 0
        assert len(client.records) == 2

        # 第二次：同样两条 → 全部走更新，不新增
        r2 = writer.write_batch(events)
        assert r2["created"] == 0, f"预期新增 0，实际 {r2}"
        assert r2["updated"] == 2, f"预期更新 2，实际 {r2}"
        assert len(client.records) == 2, "飞书侧记录数不应增加"

        # 第三次：新增一条 + 重复一条 → 1 新增 1 更新
        r3 = writer.write_batch([events[0], _event("王五", "110101199003033456")])
        assert r3["created"] == 1, f"预期新增 1，实际 {r3}"
        assert r3["updated"] == 1, f"预期更新 1，实际 {r3}"
        assert len(client.records) == 3


def test_e2e_record_id_mapping_persisted():
    """新增后 record_id 必须落盘，否则重启后重复消费会产生重复行"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "map.json")
        store = SyncMapStore(path)
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        writer.write_batch([_event("张三", "110101199001011234")])

        # 新建 store 实例（模拟进程重启后重新加载）
        store2 = SyncMapStore(path)
        rid = store2.get_record_id("2026-11-10", "110101199001011234")
        assert rid is not None, "record_id 未落盘"
        assert client.records[rid]["姓名"] == "张三"


def test_e2e_different_date_same_person_creates_new_row():
    """同一人不同日期 → 飞书里是两行（每天一行是打卡表语义）"""
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        r = writer.write_batch([
            _event("张三", "110101199001011234", "2026-11-10 08:00:00"),
            _event("张三", "110101199001011234", "2026-11-11 08:00:00"),
        ])
        assert r["created"] == 2, f"预期新增 2，实际 {r}"
        assert len(client.records) == 2


def test_e2e_skip_event_without_id_number():
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        r = writer.write_batch([{"memberName": "无证件", "punchTime": "2026-11-10 08:00:00"}])
        assert r["skipped"] == 1, f"预期跳过 1，实际 {r}"
        assert r["created"] == 0
        assert len(client.records) == 0


def test_e2e_date_field_is_millis():
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        writer.write_batch([_event("张三", "110101199001011234")])
        rec = list(client.records.values())[0]
        assert isinstance(rec["打卡日期"], int), "打卡日期必须是毫秒时间戳"
        assert isinstance(rec["打卡时间"], int), "打卡时间必须是毫秒时间戳"
        assert rec["打卡日期"] > 1_700_000_000_000


def test_e2e_punch_date_is_date_only():
    """打卡日期列只保留日期（当天零点），不应带出时分秒"""
    from datetime import datetime

    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        writer.write_batch([_event("张三", "110101199001011234", "2026-11-10 08:32:00")])
        rec = list(client.records.values())[0]

        date_dt = datetime.fromtimestamp(rec["打卡日期"] / 1000)
        time_dt = datetime.fromtimestamp(rec["打卡时间"] / 1000)
        assert date_dt.hour == 0 and date_dt.minute == 0, "打卡日期应归零到当天零点"
        assert time_dt.hour == 8 and time_dt.minute == 32, "打卡时间应保留时分秒"


def test_e2e_punch_date_falls_back_to_punch_time():
    """ERP 消息只带 punchTime 时，打卡日期列仍要有值"""
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        # 事件里没有 punchDate 字段
        ev = _event("张三", "110101199001011234", "2026-11-10 08:32:00")
        assert "punchDate" not in ev

        writer.write_batch([ev])
        rec = list(client.records.values())[0]
        assert "打卡日期" in rec, "打卡日期列不应缺失"
        assert isinstance(rec["打卡日期"], int)


def test_e2e_from_raw_mq_message():
    """从原始 MQ 消息体一路走到飞书写入"""
    import json

    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        raw = json.dumps({
            "events": [
                {"employeeName": "雷天林", "idCard": "510228196402241013",
                 "project": "广州华润白鹅潭项目", "team": "一班",
                 "signTime": "2026-08-21T08:32:00"},
            ]
        })
        rename = {
            "employeeName": "memberName",
            "idCard": "identificationNumber",
            "project": "projectName",
            "team": "teamName",
            "signTime": "punchTime",
        }
        events = normalize_events(raw, rename)
        r = writer.write_batch(events)

        assert r["created"] == 1, f"预期新增 1，实际 {r}"
        rec = list(client.records.values())[0]
        assert rec["姓名"] == "雷天林"
        assert rec["身份证号"] == "510228196402241013"
        assert rec["项目名称"] == "广州华润白鹅潭项目"
        assert isinstance(rec["打卡时间"], int)


def test_e2e_batch_over_500_is_split():
    """超过 500 条要自动分批（飞书单次上限）"""
    with tempfile.TemporaryDirectory() as d:
        store = SyncMapStore(os.path.join(d, "map.json"))
        client = FakeFeishuClient()
        writer = FeishuWriter(client=client, store=store)

        events = [_event(f"员工{i}", f"1101011990{i:02d}0000{i:04d}") for i in range(600)]
        r = writer.write_batch(events)

        assert r["created"] == 600, f"预期新增 600，实际 {r}"
        assert client.create_calls == 2, f"600 条应分 2 批，实际 {client.create_calls}"
        assert len(client.records) == 600


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all e2e tests passed")
