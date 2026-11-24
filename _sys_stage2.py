# -*- coding: utf-8 -*-
"""以 LocalSystem 身份执行的阶段 2：拉起「保单分析监听」守护（Session 0 常驻）。

由临时 Windows 服务（SYSTEM 身份）调用。职责：
  ① 清理已存在的保单分析监听进程（锁文件 PID + 进程扫描）
  ② 以 DETACHED_PROCESS 拉起 policy_analysis_watchdog.py
  ③ 校验锁文件 / 日志是否生成，写出结果供调用方核对

与 _sys_stage1.py（MQ 直连消费者）完全独立，互不干扰。
"""

import json
import os
import subprocess
import sys
import time

REPO = r"C:\insurance-automation"
RESULT_PATH = os.path.join(REPO, "_sys_stage2_result.json")
LOG_PATH = os.path.join(REPO, "_sys_stage2.log")
LOCK_PATH = os.path.join(REPO, ".policy_analysis_watchdog.lock")
WATCHDOG_LOG = os.path.join(REPO, "policy_analysis_watchdog.log")
WATCHER_LOG = os.path.join(REPO, "policy_analysis.log")

WATCHDOG = "policy_analysis_watchdog.py"
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
        return -1, "run failed: %r" % (e,)


def scan_policy_pids():
    """扫描命令行含 policy_analysis 的 python 进程 PID"""
    rc, out = run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { "
         "$_.Name -like 'python*' -and $_.CommandLine -like '*policy_analysis*' } "
         "| ForEach-Object { $_.ProcessId }"], timeout=45)
    pids = []
    for tok in out.split():
        if tok.isdigit():
            p = int(tok)
            if p not in pids:
                pids.append(p)
    return pids


def kill(pid):
    rc, out = run(["taskkill", "/F", "/PID", str(pid)], timeout=30)
    log("taskkill PID %d -> rc=%s %s" % (pid, rc, out.strip()[:120]))
    return rc == 0


def main():
    result = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

    # ① 清理旧实例：锁文件 PID + 进程扫描
    targets = []
    if os.path.exists(LOCK_PATH):
        try:
            old = int(open(LOCK_PATH, "r", encoding="utf-8").read().strip())
            if old > 0:
                targets.append(old)
        except Exception:
            pass
    try:
        os.remove(LOCK_PATH)
    except Exception:
        pass
    for pid in scan_policy_pids():
        if pid not in targets:
            targets.append(pid)

    killed = []
    for pid in targets:
        if kill(pid):
            killed.append(pid)
    result["old_pids_found"] = targets
    result["old_killed"] = killed
    result["steps"].append("old instances stopped")
    time.sleep(1.5)

    # ② 拉起守护
    started = False
    try:
        subprocess.Popen(
            [PYTHONW, WATCHDOG],
            cwd=REPO,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            close_fds=True,
        )
        started = True
        log("保单分析监听守护已启动")
    except Exception as e:
        log("启动保单分析监听失败: %s" % e)
    result["watchdog_started"] = started
    result["steps"].append("watchdog started" if started else "watchdog FAILED")

    # ③ 校验
    time.sleep(8.0)
    result["lock_file_exists"] = os.path.exists(LOCK_PATH)
    result["lock_pid"] = (open(LOCK_PATH, "r", encoding="utf-8").read().strip()
                          if os.path.exists(LOCK_PATH) else "")
    result["watchdog_log_exists"] = os.path.exists(WATCHDOG_LOG)
    result["watcher_log_exists"] = os.path.exists(WATCHER_LOG)
    result["running_pids"] = scan_policy_pids()
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("写结果失败: %s" % e)
    log("阶段2完成: %s" % json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
