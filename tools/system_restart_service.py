#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""以 SYSTEM 身份终止 8765 服务进程（由 SYSTEM 计划任务调用）。

背景：
    8765 服务由 SYSTEM 身份的 watchdog 拉起（进程链 pythonw → watchdog → server）。
    普通权限 / 提权到 Administrator 都无法终止它：
      · taskkill → 拒绝访问
      · OpenProcess → 失败（管理员令牌未分配 SeDebugPrivilege，
        AdjustTokenPrivileges 返回 1300 ERROR_NOT_ALL_ASSIGNED）

因此改用「SYSTEM 计划任务」执行本脚本 —— SYSTEM 身份天然可以终止该进程。
watchdog 检测到服务退出（proc.poll() != None）后会自动拉起新进程，
从而加载最新代码。

用法（不要手工运行，由 tools/system_restart_service.ps1 注册计划任务后触发）：
    1) 注册一次性 SYSTEM 计划任务：
         $a = New-ScheduledTaskAction -Execute 'C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe' `
                                      -Argument '"C:\insurance-automation\tools\system_restart_service.py"'
         $p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
         $t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(3)
         Register-ScheduledTask -TaskName 'TempKill8765' -Action $a -Principal $p -Trigger $t -Force
    2) Start-ScheduledTask -TaskName 'TempKill8765'
    3) 等待 watchdog 拉起（RESTART_DELAY=3s，bridge 5s）
    4) Unregister-ScheduledTask -TaskName 'TempKill8765' -Confirm:$false

配套：tools/restart_service_8765.py 是**普通权限**版本（用于非 SYSTEM 进程）。
"""
import ctypes
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOG = r"C:\insurance-automation\data\_system_kill.log"
PORT_LOCK = r"C:\insurance-automation\.server.port.lock"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        print(msg)
    except Exception:
        pass


def find_listener_pid() -> int | None:
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=15,
            encoding="mbcs", errors="replace",
        ).stdout
    except Exception as e:
        log(f"netstat 失败: {e}")
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[3].upper() != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] != "8765":
            continue
        try:
            return int(parts[-1])
        except ValueError:
            continue
    return None


def main() -> int:
    log("=== SYSTEM kill 脚本启动 ===")
    pid = find_listener_pid()
    if not pid:
        log("8765 未监听，无需终止")
        return 0
    log(f"目标 PID: {pid}")

    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        log(f"OpenProcess 失败 (err={ctypes.get_last_error()})")
        return 1
    try:
        ok = ctypes.windll.kernel32.TerminateProcess(handle, 1)
        log(f"TerminateProcess -> {bool(ok)}")
        if not ok:
            return 1
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    # 等待进程真正退出（watchdog 靠 proc.poll() 感知）
    for _ in range(20):
        time.sleep(0.5)
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            log("目标进程已退出")
            break
        ctypes.windll.kernel32.CloseHandle(h)
    else:
        log("⚠️ 目标进程 10s 后仍存活")

    # 清理端口锁（若残留），避免新 server 误判
    try:
        if os.path.exists(PORT_LOCK):
            with open(PORT_LOCK, encoding="utf-8") as f:
                old = f.read().strip()
            log(f"端口锁残留 PID={old}，尝试清理")
            os.remove(PORT_LOCK)
            log("端口锁已清理")
    except Exception as e:
        log(f"端口锁清理异常: {e}")

    log("=== SYSTEM kill 脚本结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
