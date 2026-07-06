"""端到端验证：用户场景「我叫黄国俊，记住我」+ 「我的名字叫什么？」"""
import json
import sys
import time
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

USER_ID = f"e2e_user_{int(time.time())}"


def parse_sse(raw):
    out = []
    cur = None
    for line in raw.splitlines():
        if line.startswith("event:"):
            cur = line[6:].strip()
        elif line.startswith("data:") and cur:
            try:
                out.append((cur, json.loads(line[5:].strip())))
            except Exception:
                pass
            cur = None
    return out


def main():
    from fastapi.testclient import TestClient
    from api.main import app

    # 清理旧的长期事实
    db_path = ROOT / "db" / "chat.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "DELETE FROM long_term_facts WHERE user_id=?", (USER_ID,)
                )
                conn.commit()
        except Exception:
            pass

    with TestClient(app) as client:
        # 创建会话
        sess = client.post(
            "/api/v1/chat/sessions",
            json={"user_id": USER_ID, "session_title": "测试会话"},
        ).json()
        sid = sess["session_id"]
        print(f"会话: {sid}")
        print(f"user_id: {USER_ID}\n")

        # 第 1 轮
        print("=" * 60)
        print('第 1 轮: "我叫黄国俊，记住我"')
        print("=" * 60)
        with client.stream(
            "POST",
            "/api/v1/react-agent/chat",
            json={
                "message": "我叫黄国俊，记住我",
                "session_id": sid,
                "stream": True,
            },
            timeout=120,
        ) as r:
            raw1 = "".join(r.iter_text())
        events1 = parse_sse(raw1)
        done1 = next((d for t, d in events1 if t == "done"), None)
        full1 = done1["full_text"] if done1 else ""
        print(f"助手: {full1[:200]}")
        print(
            f"事件数: {len(events1)}, 耗时: {done1.get('duration_ms') if done1 else '?'}ms"
        )

        # 等待 fact 抽取
        time.sleep(2)

        # 验证长期事实
        from core.memory.long_term_store import LongTermStore
        lt = LongTermStore(db_path=db_path)
        facts = lt.get_all(USER_ID)
        print(f"\n长期事实抽取 ({len(facts)} 条):")
        for f in facts:
            print(f"  - [{f['category']}] {f['text']}")
        if not facts:
            print("  ⚠️ 未抽取到任何事实！")
            return 1

        # 第 2 轮
        print("\n" + "=" * 60)
        print('第 2 轮: "我的名字叫什么？"')
        print("=" * 60)
        with client.stream(
            "POST",
            "/api/v1/react-agent/chat",
            json={
                "message": "我的名字叫什么？",
                "session_id": sid,
                "stream": True,
            },
            timeout=120,
        ) as r:
            raw2 = "".join(r.iter_text())
        events2 = parse_sse(raw2)
        done2 = next((d for t, d in events2 if t == "done"), None)
        full2 = done2["full_text"] if done2 else ""
        print(f"助手: {full2[:300]}")
        print(
            f"事件数: {len(events2)}, 耗时: {done2.get('duration_ms') if done2 else '?'}ms"
        )

        # 验证
        if "黄国俊" in full2:
            print("\n✅ 测试通过：助手在第 2 轮正确回忆「黄国俊」")
            return 0
        else:
            print("\n❌ 测试失败：助手未能在第 2 轮回忆「黄国俊」")
            return 1


if __name__ == "__main__":
    sys.exit(main())
