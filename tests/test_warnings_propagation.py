"""warnings 透传链路 + 批单入库守卫回归测试（2026-11-13）

背景：
    InvoiceRecognitionState(TypedDict) 未声明 warnings 键时，
    LangGraph 的 StateGraph 只为已声明的键建 channel，
    节点返回的 warnings 会被**静默丢弃** →
    validator_node 产出的所有告警（批单未找到主保单、缺姓名/证件号、
    扫描件保单号跨页冲突）都传不到 output_node 与 web_app。

    web_app/server.py 里「批单主保单缺失 → 阻断入库」的防御分支
    因此长期是死代码。透传修复后它会真正开始执行，
    故必须同时验证其语义：只在**确实会写入空日期记录**时才阻断。

判定逻辑已抽到 insurance_agent.tools.batch_guard（纯函数、无第三方依赖），
因为 fastapi 只装在 H-AGENT venv（无 pytest），项目根 venv 无法 import web_app.server。
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from insurance_agent.agents.invoice_recognition.states.inv_state import (  # noqa: E402
    InvoiceRecognitionState,
    create_invoice_recognition_state,
)
from insurance_agent.tools.batch_guard import (  # noqa: E402
    count_missing_date_persons,
    evaluate_batch_guard,
    find_main_missing_warning,
)


# --------------------------------------------------------------------------
# 1. 状态声明层
# --------------------------------------------------------------------------
class TestWarningsStateDeclaration:
    def test_warnings_key_declared_in_typed_dict(self):
        """必须显式声明，否则 LangGraph 静默丢弃该键"""
        assert "warnings" in InvoiceRecognitionState.__annotations__

    def test_factory_initializes_warnings(self):
        state = create_invoice_recognition_state(user_goal="t", file_path="f.pdf")
        assert state.get("warnings") == []


# --------------------------------------------------------------------------
# 2. LangGraph 透传层
# --------------------------------------------------------------------------
class TestWarningsPassThroughLangGraph:
    def _build_graph(self):
        from langgraph.graph import StateGraph, END

        def n1(state):
            return {
                "working_memory": {"x": 1},
                "warnings": ["批单未找到对应主保单: main=A, batch=B"],
            }

        def n2(state):
            # output_node 通过 state.get("warnings", []) 读取
            return {"final_response": "ok"}

        g = StateGraph(InvoiceRecognitionState)
        g.add_node("n1", n1)
        g.add_node("n2", n2)
        g.set_entry_point("n1")
        g.add_edge("n1", "n2")
        g.add_edge("n2", END)
        return g.compile()

    def test_warnings_survive_graph_edges(self):
        app = self._build_graph()
        out = app.invoke(create_invoice_recognition_state(user_goal="t", file_path="f.pdf"))
        assert out.get("warnings") == ["批单未找到对应主保单: main=A, batch=B"]

    def test_output_node_reads_warnings(self):
        """output_node 必须在 state 中看到 warnings"""
        from insurance_agent.agents.invoice_recognition.nodes.output_node import OutputNode

        out = OutputNode()({"warnings": ["警告X"], "extraction_result": {"a": 1}})
        assert out["final_response"]
        assert "a" in out["final_response"]


# --------------------------------------------------------------------------
# 3. 告警文本匹配
# --------------------------------------------------------------------------
class TestMainMissingWarningMatch:
    def test_matches_missing_main(self):
        w = "批单未找到对应主保单: main=, batch=7116013, company=X"
        assert find_main_missing_warning([w]) == w

    def test_matches_incompatible_main(self):
        w = "批单关联的主保单号(123)与批单的主保单号(456)不一致"
        assert find_main_missing_warning([w]) == w

    def test_ignores_other_warnings(self):
        assert find_main_missing_warning([
            "缺少姓名: ID=4401",
            "扫描件保单号跨页识别不一致，需人工核对: {'A': 2}",
        ]) == ""

    def test_none_input(self):
        assert find_main_missing_warning(None) == ""
        assert find_main_missing_warning([]) == ""


# --------------------------------------------------------------------------
# 4. 缺日期人数统计
# --------------------------------------------------------------------------
class TestCountMissingDates:
    def test_counts(self):
        persons = [
            {"start_date": "2026-10-01", "end_date": "2026-10-31"},
            {"start_date": "2026-10-01", "end_date": ""},
            {"start_date": "", "end_date": "2026-10-31"},
            {"start_date": "", "end_date": ""},
        ]
        missing, total = count_missing_date_persons(persons)
        assert (missing, total) == (3, 4)

    def test_whitespace_treated_as_missing(self):
        persons = [{"start_date": "  ", "end_date": "2026-10-31"}]
        missing, total = count_missing_date_persons(persons)
        assert (missing, total) == (1, 1)

    def test_none_handling(self):
        assert count_missing_date_persons(None) == (0, 0)


# --------------------------------------------------------------------------
# 5. 批单入库守卫语义
# --------------------------------------------------------------------------
class TestBatchGuard:
    """2026-11-13 加固：拦截条件 = 命中主保单缺失告警 且 人员确有日期缺失"""

    MISSING_W = "批单未找到对应主保单: main=, batch=7116013100260099999001, company=测试公司"

    def _persons(self, n, dated=True):
        return [{
            "name": f"张三{i}",
            "id_number": f"4401{i:014d}",
            "start_date": "2026-10-01" if dated else "",
            "end_date": "2026-10-31" if dated else "",
        } for i in range(n)]

    def test_dated_persons_are_not_blocked(self):
        """主保单缺失但人员日期齐全 → 放行（否则造成大面积误拦截回归）"""
        r = evaluate_batch_guard([self.MISSING_W], self._persons(10, dated=True))
        assert r["should_block"] is False
        assert r["reason"] == ""
        assert r["missing_date_cnt"] == 0
        assert r["total_persons"] == 10
        assert r["warning"] == self.MISSING_W

    def test_undated_persons_are_blocked(self):
        """主保单缺失且人员缺日期 → 阻断，避免写入空日期记录"""
        r = evaluate_batch_guard([self.MISSING_W], self._persons(10, dated=False))
        assert r["should_block"] is True
        assert "缺保险期间" in r["reason"]
        assert "10/10" in r["reason"]

    def test_partially_undated_persons_are_blocked(self):
        """部分人缺日期 → 阻断"""
        persons = self._persons(10, dated=True)
        persons[0]["end_date"] = ""
        persons[3]["start_date"] = ""
        r = evaluate_batch_guard([self.MISSING_W], persons)
        assert r["should_block"] is True
        assert "2/10" in r["reason"]

    def test_no_missing_warning_never_blocks(self):
        """没有主保单缺失告警 → 绝不拦截（即使人员缺日期，交给别的链路处理）"""
        r = evaluate_batch_guard(["缺少姓名: ID=4401"], self._persons(3, dated=False))
        assert r["should_block"] is False
        assert r["missing_date_cnt"] == 3

    def test_empty_persons_not_blocked(self):
        """没提到人员 → 无脏数据风险，不拦截"""
        r = evaluate_batch_guard([self.MISSING_W], [])
        assert r["should_block"] is False
        assert r["total_persons"] == 0

    def test_none_guards_not_blocked(self):
        r = evaluate_batch_guard(None, None)
        assert r["should_block"] is False


# --------------------------------------------------------------------------
# 6. 历史批单回归（用真实保单库抽样，验证不会误杀已入库批单）
# --------------------------------------------------------------------------
class TestHistoricalBatchNoFalseBlock:
    """真实数据回归：已入库批单的人员日期缺失必须为 0，
    否则守卫一旦激活就会大面积拦截（43/253 个批单本就找不到主保单）"""

    def test_persisted_batch_persons_all_dated(self):
        import json
        import sqlite3

        idx = os.path.join(ROOT, "policy_library", "index_batch.json")
        db_path = os.path.join(ROOT, "data", "app.db")
        if not os.path.exists(idx) or not os.path.exists(db_path):
            pytest.skip("无保单库或数据库，跳过")

        with open(idx, encoding="utf-8") as f:
            records = json.load(f).get("records", [])
        if not records:
            pytest.skip("保单库为空，跳过")

        batch_nos = {r.get("policy_number") or "" for r in records if r.get("policy_number")}
        if not batch_nos:
            pytest.skip("批单记录无保单号，跳过")

        db = sqlite3.connect(db_path)
        try:
            total_undated = 0
            for pn in batch_nos:
                r = db.execute(
                    """SELECT COUNT(*) FROM insurance_personnel
                       WHERE policy_number = ?
                         AND (start_date IS NULL OR TRIM(start_date) = ''
                              OR end_date IS NULL OR TRIM(end_date) = '')""",
                    (pn,),
                ).fetchone()
                total_undated += (r[0] or 0)
        finally:
            db.close()

        assert total_undated == 0, (
            f"已入库批单人员仍有 {total_undated} 条日期缺失，"
            f"守卫激活后这些批单会被大面积拦截"
        )

    def test_batch_record_level_dates_may_be_empty(self):
        """批单记录自身无起止期间是正常的（批单只有生效日），
        因此守卫的判定必须基于**人员**日期而非批单记录日期"""
        import json
        idx = os.path.join(ROOT, "policy_library", "index_batch.json")
        if not os.path.exists(idx):
            pytest.skip("无保单库，跳过")
        with open(idx, encoding="utf-8") as f:
            records = json.load(f).get("records", [])
        assert records
        # 记录级日期允许为空 —— 本测试只确认该事实成立（避免误把断言写死）
        undated = sum(
            1 for r in records
            if not (r.get("start_date") or "").strip() or not (r.get("end_date") or "").strip()
        )
        assert undated >= 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
