"""直连链路自检脚本（probe.py）的离线测试

不发网络请求、不连 MQ、不连飞书，验证自检逻辑的判定是否正确。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_feishu_direct.mapper import DEFAULT_FIELD_MAPPING  # noqa: E402
from erp_feishu_direct.probe import (  # noqa: E402
    Checker,
    check_feishu,
    check_mq,
    check_write_permission,
)


class FakeFeishuClient:
    """模拟飞书 Bitable 客户端（只实现 probe 用到的方法）"""

    def __init__(self, tables=None, fields=None, fail_on_create=None):
        self._tables = tables or []
        self._fields = fields or []
        self._fail_on_create = fail_on_create
        self.records = {}
        self.deleted = []
        self._seq = 0

    def get_token(self):
        return "t-fake"

    def list_tables(self):
        return self._tables

    def list_fields(self, table_id=""):
        return self._fields

    def resolve_table_id(self, table_name=""):
        for t in self._tables:
            if t.get("name") == table_name:
                return t.get("table_id", "")
        raise ValueError("找不到")

    def batch_create(self, records, table_id="", client_token=""):
        if self._fail_on_create:
            from insurance_agent.infrastructure.feishu_bitable_client import FeishuBitableError

            raise FeishuBitableError(self._fail_on_create, "模拟写入失败", 400)
        out = []
        for item in records:
            self._seq += 1
            rid = f"rec{self._seq:04d}"
            self.records[rid] = dict(item.get("fields", {}))
            out.append({"record_id": rid, "fields": item.get("fields", {})})
        return out

    def batch_delete(self, record_ids, table_id=""):
        self.deleted.extend(record_ids)
        return len(record_ids)

    def _request(self, method, path, json_body=None, params=None, retry_on_auth_error=True):
        return {"items": [
            {"record_id": rid, "fields": f} for rid, f in self.records.items()
        ]}


def _cfg(app_token="bascnFake", table_id="tblFake", table_name=""):
    return {
        "feishu": {
            "app_id": "cli_fake",
            "app_secret": "secret",
            "app_token": app_token,
            "table_id": table_id,
            "table_name": table_name,
            "timeout": 5,
        },
        "mq": {
            "host": "http://fake", "port": 80, "instance_id": "MQ_INST_FAKE",
            "access_key": "ak", "secret_key": "sk",
            "topic": "JS_PROD_MQ", "tag": "CLOCK_RECORD_CREATE",
            "group": "feishu-direct-sync", "use_tls": False,
        },
    }


def _all_fields():
    """构造一个与映射表完全对齐的字段定义"""
    return [
        {"field_name": name, "type": 5 if name in ("打卡日期", "打卡时间") else 1}
        for name in DEFAULT_FIELD_MAPPING
    ]


def _levels(ck):
    return [i["level"] for i in ck.items]


def _titles(ck):
    return [i["title"] for i in ck.items]


# ==================== 配置与消费组 ====================


def test_probe_blocks_group_name_colliding_with_bridge():
    """与现有桥接消费组重名 → 必须报错拦截"""
    cfg = _cfg()
    cfg["mq"]["group"] = "insurance-automation"
    ck = Checker()
    check_mq(cfg, ck)
    assert "error" in _levels(ck)
    assert any("重名" in t for t in _titles(ck))


def test_probe_allows_new_group_name():
    """新组名不应触发重名拦截（后续步骤会因 SDK 缺失/网络问题告警，但不应是「重名」）"""
    cfg = _cfg()
    cfg["mq"]["group"] = "feishu-direct-sync"
    ck = Checker()
    check_mq(cfg, ck)
    assert not any("重名" in t for t in _titles(ck))


# ==================== 飞书表结构 ====================


def test_probe_reports_all_columns_present():
    """字段齐全 + 日期列类型正确 → 不应有 error"""
    client = FakeFeishuClient(
        tables=[{"table_id": "tblFake", "name": "打卡明细"}],
        fields=_all_fields(),
    )
    ck = Checker()
    cfg = _cfg()
    cfg["feishu"]["table_id"] = ""
    cfg["feishu"]["table_name"] = "打卡明细"

    # 直接替换 check_feishu 内部的 client 构造：monkeypatch 掉 load_client_from_config
    import erp_feishu_direct.probe as probe_mod

    orig = probe_mod.load_client_from_config
    probe_mod.load_client_from_config = lambda c: client
    try:
        check_feishu(cfg, ck)
    finally:
        probe_mod.load_client_from_config = orig

    assert "error" not in _levels(ck), [i for i in ck.items if i["level"] == "error"]
    assert any("全部存在" in t for t in _titles(ck))


def test_probe_reports_missing_column():
    """缺列 → 必须报错并点名缺哪几列"""
    fields = _all_fields()
    fields = [f for f in fields if f["field_name"] != "班组"]
    client = FakeFeishuClient(
        tables=[{"table_id": "tblFake", "name": "打卡明细"}], fields=fields
    )
    ck = Checker()
    cfg = _cfg()

    import erp_feishu_direct.probe as probe_mod

    orig = probe_mod.load_client_from_config
    probe_mod.load_client_from_config = lambda c: client
    try:
        check_feishu(cfg, ck)
    finally:
        probe_mod.load_client_from_config = orig

    assert "error" in _levels(ck)
    missing_item = [i for i in ck.items if "缺少映射所需的列" in i["title"]]
    assert missing_item, _titles(ck)
    assert "班组" in missing_item[0]["detail"]


def test_probe_reports_wrong_date_field_type():
    """「打卡日期」列类型是文本而非日期 → 必须报错"""
    fields = _all_fields()
    for f in fields:
        if f["field_name"] == "打卡日期":
            f["type"] = 1  # 改成文本
    client = FakeFeishuClient(
        tables=[{"table_id": "tblFake", "name": "打卡明细"}], fields=fields
    )
    ck = Checker()
    cfg = _cfg()

    import erp_feishu_direct.probe as probe_mod

    orig = probe_mod.load_client_from_config
    probe_mod.load_client_from_config = lambda c: client
    try:
        check_feishu(cfg, ck)
    finally:
        probe_mod.load_client_from_config = orig

    assert "error" in _levels(ck)
    assert any("打卡日期" in t and "类型错误" in t for t in _titles(ck))


# ==================== 写测试 ====================


def test_probe_write_test_creates_then_deletes():
    """--write-test：写一条 → 读回 → 删除，测试记录不能残留"""
    client = FakeFeishuClient(
        tables=[{"table_id": "tblFake", "name": "打卡明细"}], fields=_all_fields()
    )
    client._table_id = "tblFake"
    client._app_token = "bascnFake"

    ck = Checker()
    check_write_permission(client, ck)

    assert "error" not in _levels(ck), [i for i in ck.items if i["level"] == "error"]
    assert len(client.records) == 1
    assert len(client.deleted) == 1, "测试记录必须被删除，不能残留在多维表格里"
    assert any("写入测试成功" in t for t in _titles(ck))
    assert any("已清理" in t for t in _titles(ck))


def test_probe_write_test_cleans_up_even_on_failure():
    """写入抛错时不应残留记录"""
    client = FakeFeishuClient(
        tables=[{"table_id": "tblFake", "name": "打卡明细"}],
        fields=_all_fields(),
        fail_on_create=1254064,
    )
    client._table_id = "tblFake"
    client._app_token = "bascnFake"

    ck = Checker()
    check_write_permission(client, ck)

    assert "error" in _levels(ck)
    assert any("1254064" in i["title"] for i in ck.items)
    assert any("日期列类型不对" in i["detail"] for i in ck.items)
    assert len(client.records) == 0
