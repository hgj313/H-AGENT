# -*- coding: utf-8 -*-
"""停止当前会话（Session 1）里的 erp_feishu_direct 直连消费者与 watchdog。

用途：让位给即将在 Session 0（LocalSystem）常驻的正式消费者实例，
避免同一消费组内出现两个消费者实例互相分流。

用法：python _stop_session1.py [--dry]
"""

import os
import subprocess
import sys
import time


def run(cmd, timeout=45):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        return r.returncode, out
    except Exception as e:
        return -1, "failed: %r" % (e,)


PS = [
    "powershell", "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'erp_feishu_direct' } "
    "| ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.SessionId)|$($_.CommandLine)\" }",
]


def find():
    rc, out = run(PS)
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        pid = int(parts[0].strip())
        rows.append({
            "pid": pid,
            "ppid": int(parts[1]) if parts[1].strip().isdigit() else 0,
            "session": parts[2].strip(),
            "cmd": parts[3].strip() if len(parts) > 3 else "",
        })
    # 排除本查询进程自身（命令行里含匹配串，会误杀）
    rows = [r for r in rows if "Get-CimInstance" not in r["cmd"]]
    return rows


def main():
    dry = "--dry" in sys.argv
    rows = find()
    if not rows:
        print("未找到 erp_feishu_direct 相关进程")
        return 0
    print("发现 %d 个相关进程：" % len(rows))
    for r in rows:
        print("  PID=%d PPID=%d Session=%s | %s" % (r["pid"], r["ppid"], r["session"], r["cmd"][:110]))
    if dry:
        return 0

    # 先停 watchdog（父），再停消费者（子）
    ordered = sorted(rows, key=lambda r: 1 if "watchdog" in r["cmd"] else 0)
    for r in ordered:
        try:
            os.kill(r["pid"], 9)
            print("  已终止 PID %d" % r["pid"])
        except Exception as e:
            print("  终止 PID %d 失败: %r" % (r["pid"], e))
    time.sleep(2)

    rc, out = run(["netstat", "-ano", "-p", "TCP"], timeout=30)
    for line in out.splitlines():
        p = line.split()
        if len(p) < 5 or p[3].upper() != "LISTENING":
            continue
        try:
            port = int(p[1].rsplit(":", 1)[1])
        except ValueError:
            continue
        if port in (8767, 8768):
            print("  端口 %d 仍被 PID %s 占用" % (port, p[4]))
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
