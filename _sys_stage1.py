# -*- coding: utf-8 -*-
"""以 LocalSystem 身份执行的阶段 1 收尾脚本。

由临时 Windows 服务（SYSTEM 身份）调用。职责：
  ① 终止残留的 MQ bridge（3840 / 7044）—— watchdog 已死，不会再拉起
  ② 启动 erp_feishu_direct 直连消费者守护（Session 0 常驻）
  ③ 写出执行结果，供调用方核对
"""

import json
import os
import subprocess
import sys
import time

REPO = r"C:\insurance-automation"
RESULT_PATH = os.path.join(REPO, "_sys_stage1_result.json")
LOG_PATH = os.path.join(REPO, "_sys_stage1.log")

DIRECT_WATCHDOG = "erp_feishu_direct_watchdog.py"
PYTHONW = os.path.join(REPO, "H-AGENT", ".venv", "Scripts", "pythonw.exe")

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def log(msg):
    line = "[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def decode(raw):
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, decode(r.stdout) + decode(r.stderr)
    except Exception as e:
        return -1, "run failed: %s" % e


def pids_by_port(port):
    pids = []
    rc, out = run(["netstat", "-ano", "-p", "TCP"], timeout=25)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        try:
            lport = int(local.rsplit(":", 1)[1])
        except ValueError:
            continue
        if lport != port or parts[3].upper() != "LISTENING":
            continue
        if parts[4].isdigit():
            pid = int(parts[4])
            if pid not in pids:
                pids.append(pid)
    return pids


def parent_pid(pid):
    rc, out = run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\").ParentProcessId" % pid],
        timeout=25)
    for line in reversed(out.splitlines()):
        t = line.strip()
        if t.isdigit():
            return int(t)
    return 0


def python_pids():
    rc, out = run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } "
         "| ForEach-Object { $_.ProcessId }"], timeout=45)
    pids = []
    for tok in out.split():
        if tok.isdigit():
            pid = int(tok)
            if pid not in pids:
                pids.append(pid)
    return pids


def kill(pid):
    rc, out = run(["taskkill", "/F", "/PID", str(pid)], timeout=30)
    log("taskkill PID %d -> rc=%s %s" % (pid, rc, out.strip()[:120]))
    return rc == 0


def main():
    result = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

    # ① 停 bridge：8767 端口占用者 + 其 python 祖先
    bridge_pids = pids_by_port(8767)
    py = python_pids()
    targets = list(bridge_pids)
    for pid in bridge_pids:
        cur = pid
        for _ in range(4):
            p = parent_pid(cur)
            if not p or p in targets:
                break
            if p in py:
                targets.append(p)
            cur = p
    killed = []
    for pid in targets:
        if kill(pid):
            killed.append(pid)
    result["bridge_pids_found"] = bridge_pids
    result["bridge_killed"] = killed
    result["steps"].append("bridge stopped")

    time.sleep(1.0)

    # ② 停旧消费者链路：8768 端口占用者（consumer）+ 其 watchdog 祖先
    #    必须先停旧的，否则新 watchdog 会因单实例锁冲突直接退出。
    cons_pids = pids_by_port(8768)
    cons_targets = list(cons_pids)
    for pid in cons_pids:
        cur = pid
        for _ in range(4):
            p = parent_pid(cur)
            if not p or p in cons_targets:
                break
            if p in py:
                cons_targets.append(p)
            cur = p
    cons_killed = []
    for pid in cons_targets:
        if kill(pid):
            cons_killed.append(pid)
    result["consumer_pids_found"] = cons_pids
    result["consumer_killed"] = cons_killed
    result["steps"].append("old consumer stopped")

    time.sleep(1.0)

    # ③ 起直连消费者守护
    started = False
    try:
        subprocess.Popen(
            [PYTHONW, DIRECT_WATCHDOG],
            cwd=REPO,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            close_fds=True,
        )
        started = True
        log("直连消费者守护已启动")
    except Exception as e:
        log("启动直连消费者失败: %s" % e)
    result["direct_consumer_started"] = started
    result["steps"].append("direct consumer started" if started else "direct consumer FAILED")

    time.sleep(4.0)
    result["port_8767_after"] = pids_by_port(8767)
    result["port_8768_after"] = pids_by_port(8768)
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("写结果失败: %s" % e)
    log("阶段1收尾完成: %s" % json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
