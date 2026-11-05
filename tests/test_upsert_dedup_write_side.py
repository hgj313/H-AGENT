# -*- coding: utf-8 -*-
r"""写侧去重规则回归测试（2026-11-05）

背景：排查「本地今日未参保 11 人 vs 飞书多维表格 22 人」时定位到重复数据根因 ——
同一 (姓名, 身份证号) 在库中会积累多条记录（实测 218 组，其中 195 组保单号是
「一条有 + 一条空」= 同一份保单入库了两次）。

用户约定（2026-11-05 原话）：
    "新入库的如果原数据库中存在且起止日期更久的，替换原数据。
     不然不需要新增。避免出现重复数据"

本文件覆盖 upsert_insurance_personnel / add_insurance_personnel 的写侧语义，
以及 partial UNIQUE INDEX 兜底。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from insurance_agent.infrastructure import database as dbmod  # noqa: E402


@pytest.fixture()
def tdb(tmp_path, monkeypatch):
    """独立测试库（monkeypatch DB_PATH + init_db 建表与索引）"""
    path = tmp_path / "test_app.db"
    monkeypatch.setattr(dbmod, "DB_PATH", str(path))
    dbmod.init_db()
    return str(path)


def _person(name, idn, sd, ed, pol="", status="正常", **kw):
    d = {
        "name": name,
        "id_number": idn,
        "id_type": "身份证",
        "company": "广州粤灿建设工程有限公司",
        "start_date": sd,
        "end_date": ed,
        "job_title": "木工",
        "birth_date": "",
        "insurance_company": "华安财产保险",
        "policy_number": pol,
        "file_name": "test.pdf",
        "status": status,
    }
    d.update(kw)
    return d


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM insurance_personnel ORDER BY id")]
    finally:
        conn.close()


# ---------------- 1. 核心：同一人只留一条 ----------------

def test_same_person_different_policy_does_not_duplicate(tdb):
    """同一人换保单号再入库 → 不得新增第二行（本次重复数据的直接成因）"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL001")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL002")])
    rows = _rows(tdb)
    assert len(rows) == 1, f"同一人应只留 1 条，实际 {len(rows)} 条"
    # 区间等价 → 保留原记录，不因保单号不同而新增
    assert rows[0]["policy_number"] == "POL001"


def test_newer_period_replaces(tdb):
    """新数据起止更久 → 替换原记录"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-06-30", pol="POL001")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-07-01", "2026-12-31", pol="POL002")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["start_date"] == "2026-07-01"
    assert rows[0]["end_date"] == "2026-12-31"
    assert rows[0]["policy_number"] == "POL002"


def test_older_period_is_skipped(tdb):
    """旧数据更久 → 不新增、不覆盖（保险型语义：不能让老保单回退）"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-07-01", "2026-12-31", pol="POL002")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-06-30", pol="POL001")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2026-12-31", "旧数据不得覆盖新数据"
    assert rows[0]["policy_number"] == "POL002"


def test_status_not_downgraded_by_older_data(tdb):
    """旧数据（失效）不得把在保人员降级"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL001")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-03-31",
                                              pol="POL002", status="失效")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["status"] == "正常", "在保人员不得被旧数据降级为失效"
    assert rows[0]["end_date"] == "2026-12-31"


# ---------------- 2. 字段合并 ----------------

def test_equal_period_fills_empty_policy_number(tdb):
    """区间等价但新数据有保单号 → 补齐空字段，不新增行"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL001")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["policy_number"] == "POL001", "空保单号应被补齐"


def test_empty_dates_do_not_wipe_real_dates(tdb):
    """新数据日期未解析出 → 保留原记录日期（11-03 踩过的坑）"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL001")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "", "", pol="POL002")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["start_date"] == "2026-01-01", "空日期不得覆盖真实起期"
    assert rows[0]["end_date"] == "2026-12-31", "空日期不得覆盖真实止期"
    assert rows[0]["status"] == "正常", "在保人员不得被误降为失效"


def test_known_period_fills_unknown_end_date(tdb):
    """旧记录止期未知（PDF 未解析出）+ 新数据在有效期内 → 用更具体的数据替换"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "", pol="POL001")])
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2099-12-31", pol="POL001")])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2099-12-31", "止期未知应被有效数据补齐"


# ---------------- 3. 批内去重 ----------------

def test_batch_dedup_keeps_better_record(tdb):
    """同一批内同人多次 → 只入库一条，且保留保得更久的那条"""
    dbmod.upsert_insurance_personnel([
        _person("张三", "440101199001011234", "2026-01-01", "2026-06-30", pol="POL001"),
        _person("张三", "440101199001011234", "2026-07-01", "2026-12-31", pol="POL002"),
    ])
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2026-12-31", "批内应保留保得更久的记录"


# ---------------- 4. 历史遗留重复行的收敛 ----------------

def test_legacy_duplicates_collapse_on_next_ingest(tdb):
    """历史遗留的多条重复行 → 下次入库时收敛为一条

    模拟「迁移前的老库」：先摘掉唯一索引造出重复行，再走一次入库。
    （迁移建索引时若发现已有重复会跳过建索引并告警，写侧仍须能收敛）
    """
    conn = sqlite3.connect(tdb)
    conn.execute("DROP INDEX IF EXISTS idx_person_name_id_uniq")
    conn.execute(
        """INSERT INTO insurance_personnel
           (name, id_number, id_type, company, start_date, end_date, job_title,
            birth_date, insurance_company, policy_number, source_file, status, created_at)
           VALUES ('张三','440101199001011234','身份证','公司A','2026-01-01','2026-06-30',
                   '木工','','华安','POL001','a.pdf','正常','2026-01-01 00:00:00')""")
    conn.execute(
        """INSERT INTO insurance_personnel
           (name, id_number, id_type, company, start_date, end_date, job_title,
            birth_date, insurance_company, policy_number, source_file, status, created_at)
           VALUES ('张三','440101199001011234','身份证','公司A','2026-01-01','2026-06-30',
                   '木工','','华安','','b.pdf','正常','2026-01-01 00:00:00')""")
    conn.commit()
    conn.close()
    assert len(_rows(tdb)) == 2

    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-06-30", pol="POL001")])
    rows = _rows(tdb)
    assert len(rows) == 1, "重复行应收敛为一条"
    assert rows[0]["policy_number"] == "POL001"


# ---------------- 5. 减保路径不受影响 ----------------

def test_deactivate_insurance_still_matches_by_policy(tdb):
    """减保仍按 policy_number 精确命中（写侧改写不得破坏减保）"""
    dbmod.upsert_insurance_personnel([_person("张三", "440101199001011234",
                                              "2026-01-01", "2026-12-31", pol="POL001")])
    n = dbmod.deactivate_insurance(["440101199001011234"], end_date="2026-06-30",
                                   policy_number="POL001")
    assert n == 1
    rows = _rows(tdb)
    assert rows[0]["status"] == "失效"
    assert rows[0]["end_date"] == "2026-06-30"


def test_deactivate_does_not_touch_other_policy(tdb):
    """减保指定批单号时，不得误伤其它保单下的记录"""
    dbmod.upsert_insurance_personnel([
        _person("张三", "440101199001011234", "2026-01-01", "2026-12-31", pol="POL001"),
        _person("李四", "440101199001011235", "2026-01-01", "2026-12-31", pol="POL002"),
    ])
    n = dbmod.deactivate_insurance(["440101199001011234"], end_date="2026-06-30",
                                   policy_number="POL001")
    assert n == 1
    rows = _rows(tdb)
    assert rows[0]["status"] == "失效"
    assert rows[1]["status"] == "正常"


# ---------------- 6. UNIQUE INDEX 兜底 ----------------

def test_unique_index_exists(tdb):
    """partial UNIQUE INDEX 必须存在（DB 层强制一人一行）"""
    conn = sqlite3.connect(tdb)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_person_name_id_uniq'"
        ).fetchone()
    finally:
        conn.close()
    assert row and row[0], "唯一索引 idx_person_name_id_uniq 未创建"
    assert "UNIQUE" in row[0]
    assert "id_number != ''" in row[0], "必须是 partial 索引（放行空 id_number）"


def test_unique_index_rejects_direct_duplicate(tdb):
    """绕过写侧直接 INSERT 同名同证件 → 必须被 DB 拦下"""
    conn = sqlite3.connect(tdb)
    try:
        for pol in ("POL001", "POL002"):
            conn.execute(
                """INSERT INTO insurance_personnel
                   (name, id_number, id_type, company, start_date, end_date, job_title,
                    birth_date, insurance_company, policy_number, source_file, status, created_at)
                   VALUES ('张三','440101199001011234','身份证','公司A','2026-01-01','2026-12-31',
                           '木工','','华安',?,'a.pdf','正常','2026-01-01 00:00:00')""", (pol,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return  # 拦住即通过
    finally:
        try:
            conn.close()
        except Exception:
            pass
    pytest.fail("唯一索引未拦住同名同证件的直接 INSERT")


def test_masked_id_collision_different_names_coexist(tdb):
    """脱敏 ID 撞车的「不同人」仍可共存（10-27 教训：唯一键必须含 name）"""
    dbmod.upsert_insurance_personnel([
        _person("张超", "34**************18", "2026-01-01", "2026-12-31", pol="POL001"),
        _person("蔡明明", "34**************18", "2026-01-01", "2026-12-31", pol="POL001"),
    ])
    rows = _rows(tdb)
    assert len(rows) == 2, "不同姓名的撞车脱敏 ID 必须都能入库"
    assert {r["name"] for r in rows} == {"张超", "蔡明明"}


# ---------------- 7. add_insurance_personnel 与 upsert 语义一致 ----------------

def test_add_insurance_personnel_same_semantics(tdb):
    """追加导入走同一套写侧规则"""
    dbmod.add_insurance_personnel([_person("张三", "440101199001011234",
                                           "2026-01-01", "2026-12-31", pol="POL001")])
    res = dbmod.add_insurance_personnel([_person("张三", "440101199001011234",
                                                 "2026-07-01", "2026-12-31", pol="POL002")])
    assert res["updated"] == 1
    assert res["added"] == 0
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2026-12-31"


def test_add_insurance_personnel_skips_older(tdb):
    """追加导入时旧数据不得覆盖新数据"""
    dbmod.add_insurance_personnel([_person("张三", "440101199001011234",
                                           "2026-07-01", "2026-12-31", pol="POL002")])
    res = dbmod.add_insurance_personnel([_person("张三", "440101199001011234",
                                                 "2026-01-01", "2026-06-30", pol="POL001")])
    assert res["skipped"] == 1
    assert res["updated"] == 0
    rows = _rows(tdb)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2026-12-31"


# ---------------- 8. 报告字段 ----------------

def test_detailed_report_counts(tdb):
    """详细报告的 added / updated / skipped 计数准确"""
    dbmod.upsert_insurance_personnel([
        _person("张三", "440101199001011234", "2026-01-01", "2026-12-31", pol="POL001"),
        _person("王五", "440101199001011236", "2026-07-01", "2026-12-31", pol="POL004"),
    ])
    report = dbmod.upsert_insurance_personnel_detailed([
        _person("李四", "440101199001011235", "2026-01-01", "2026-12-31", pol="POL003"),
        _person("张三", "440101199001011234", "2026-07-01", "2026-12-31", pol="POL002"),
        _person("王五", "440101199001011236", "2026-01-01", "2026-06-30", pol="POL005"),
    ])
    assert report["added"] == 1      # 李四首次入库
    assert report["updated"] == 1    # 张三被替换（起期更晚）
    assert report["skipped"] == 1    # 王五旧数据更久 → 跳过
    assert report["written"] == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
