"""验证 ReactAgent 工具反馈循环修复。"""
import json
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 把仓库根加入 sys.path（脚本独立运行时不依赖 pytest 的 cwd 注入）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402


def parse_sse(raw: str):
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
    with TestClient(app) as client:
        sess = client.post(
            "/api/v1/chat/sessions", json={"user_id": "tool_test"}
        ).json()
        sid = sess["session_id"]
        print(f"sid={sid}\n")

        with client.stream(
            "POST",
            "/api/v1/react-agent/chat",
            json={
                "message": "今天日期是？",
                "session_id": sid,
                "stream": True,
            },
            timeout=120,
        ) as r:
            text = "".join(r.iter_text())

        events = parse_sse(text)
        print(f"共 {len(events)} 个事件\n")
        print("=== 事件序列 ===")
        for i, (t, d) in enumerate(events):
            seq = d.get("sequence", "?")
            if t == "message":
                content = d.get("content", "")[:40]
                kind = d.get("type")
                print(f"  [{i:02d}] seq={seq} message({kind}) {content!r}")
            elif t == "tool_call":
                name = d.get("tool_name")
                args = d.get("arguments")
                print(f"  [{i:02d}] seq={seq} tool_call {name}({args})")
            elif t == "tool_result":
                name = d.get("tool_name")
                result = d.get("result", "")[:40]
                print(f"  [{i:02d}] seq={seq} tool_result {name} = {result!r}")
            elif t == "node_update":
                node = d.get("node")
                status = d.get("status")
                msg = d.get("message", "")[:30]
                print(f"  [{i:02d}] seq={seq} node_update {node} -> {status}: {msg}")
            elif t == "thinking":
                print(f"  [{i:02d}] seq={seq} thinking stage={d.get('stage', '')}")
            elif t == "done":
                print(f"  [{i:02d}] seq={seq} DONE")
            elif t == "error":
                print(f"  [{i:02d}] seq={seq} ERROR {d.get('error')}")
        print()

        done = next((d for t, d in events if t == "done"), None)
        if done:
            full = done.get("full_text", "")
            print("=== DONE full_text ===")
            print(repr(full[:300]))
            print()
            tcs = done.get("tool_calls", [])
            print(
                f"长度: {len(full)}  工具调用: {len(tcs)}  耗时: {done.get('duration_ms')}ms"
            )


if __name__ == "__main__":
    main()
