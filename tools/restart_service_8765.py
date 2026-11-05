#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重启 8765 服务（可靠版）

为什么要专门写这个：
    · Stop-Process / taskkill 在本机会出现 "exit 1 但进程未真正终止" 的情况
    → 统一改用 ctypes 的 TerminateProcess（Windows 官方 API，进程必然终止）
    · watchdog 检测到服务崩溃后会自动拉起（proc.poll() 轮询），无需手工启动

用法：
    python tools/restart_service_8765.py
"""
import ctypes
import os
import socket
import subprocess
import sys
import time

PORT = 8765
EXPECT_EXE = ("python.exe", "pythonw.exe")


def find_listener_pid() -> int | None:
    """找出监听 8765 的进程 PID（Windows 10+ 用 netstat -ano）"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=15,
            encoding="mbcs", errors="replace",   # netstat 输出是 GBK/ANSI
        ).stdout
    except Exception as e:
        print(f"netstat 执行失败: {e}")
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        state = parts[3]
        pid = parts[-1]
        if state.upper() != "LISTENING":
            continue
        if local.rsplit(":", 1)[-1] != str(PORT):
            continue
        try:
            return int(pid)
        except ValueError:
            continue
    return None


def verify_process(pid: int) -> bool:
    """确认 PID 是 python.exe / pythonw.exe（防止 PID 复用误杀）

    ⚠️ 不用 wmic（Win11 24H2 起已弃用），改用 tasklist。
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            encoding="mbcs", errors="replace",
        ).stdout
    except Exception:
        out = ""
    low = out.lower()
    if not low.strip():
        try:
            import psutil  # type: ignore
            p = psutil.Process(pid)
            return p.name().lower() in EXPECT_EXE
        except Exception:
            return False
    return any(exe in low for exe in EXPECT_EXE)


def port_alive() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def terminate(pid: int) -> bool:
    """用 TerminateProcess 强制终止（唯一可靠方式）"""
    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        print(f"  OpenProcess 失败 (PID {pid})")
        return False
    try:
        ok = ctypes.windll.kernel32.TerminateProcess(handle, 1)
        return bool(ok)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def main():
    pid = find_listener_pid()
    if not pid:
        print(f"❌ 端口 {PORT} 未监听（服务可能已停止）")
        return 1

    print(f"当前监听 {PORT} 的进程 PID: {pid}")
    if not verify_process(pid):
        print("❌ 该 PID 不是 python.exe，拒绝终止（防 PID 复用误杀）")
        return 1
    print("  校验通过：确认为 python 进程")

    print("→ TerminateProcess 终止服务（watchdog 将自动拉起）")
    if not terminate(pid):
        print("❌ TerminateProcess 失败")
        return 1

    time.sleep(1)
    if port_alive():
        print("  端口仍在监听，等待进程完全退出...")
        for _ in range(10):
            time.sleep(0.5)
            if not port_alive():
                break

    print("→ 等待 watchdog 拉起新进程...")
    for i in range(60):
        time.sleep(1)
        new_pid = find_listener_pid()
        if new_pid and new_pid != pid:
            print(f"✅ 服务已恢复：PID {new_pid}（耗时约 {i + 1}s）")
            return 0
    print("❌ 等待超时（60s），服务未恢复")
    return 1


if __name__ == "__main__":
    sys.exit(main())
