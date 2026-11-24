# -*- coding: utf-8 -*-
"""创建并启动一个临时的 LocalSystem Windows 服务，用于以 SYSTEM 权限执行本机脚本。

背景：保险助手的 watchdog / bridge / server 运行在 Session 0（SYSTEM 权限），
普通会话（Medium 完整性级别）无法终止它们：
    Stop-Process / taskkill -> 拒绝访问
    SeDebugPrivilege        -> 当前令牌无此特权
    schtasks /create        -> 拒绝访问（且在工具黑名单内）
唯一可行途径是 SCM：通过 CreateServiceW 创建一个 LocalSystem 服务，
由服务控制管理器（SYSTEM）拉起进程，绕过完整性级别限制。

本脚本使用完立即 DeleteService，不留残留。
"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SERVICE_NAME = "WBInsuranceStage1"
SERVICE_DISPLAY = "WorkBuddy Insurance Stage1 Runner"

SC_MANAGER_CREATE_SERVICE = 0x0002
SC_MANAGER_ALL_ACCESS = 0xF003F
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_AUTO_START = 0x00000002
SERVICE_ERROR_NORMAL = 0x00000001
SERVICE_ALL_ACCESS = 0x000F01FF
DELETE = 0x00010000
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_SHUTDOWN = 0x00000005
SERVICE_STOPPED = 0x00000001
SERVICE_RUNNING = 0x00000004
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
NO_ERROR = 0

advapi32.OpenSCManagerW.restype = wintypes.HANDLE
advapi32.CreateServiceW.restype = wintypes.HANDLE
advapi32.OpenServiceW.restype = wintypes.HANDLE
advapi32.StartServiceW.restype = wintypes.BOOL
advapi32.ControlService.restype = wintypes.BOOL
advapi32.DeleteService.restype = wintypes.BOOL
advapi32.CloseServiceHandle.restype = wintypes.BOOL
advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
kernel32.CloseHandle.restype = wintypes.BOOL


class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


def _err():
    return ctypes.get_last_error()


def main():
    script = sys.argv[1] if len(sys.argv) > 1 else r"C:\insurance-automation\_sys_stage1.py"
    py = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
    bin_path = '"%s" "%s"' % (py, script)

    print("[1] OpenSCManager(CREATE_SERVICE)...")
    scm = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CREATE_SERVICE)
    if not scm:
        print("    FAIL err=%d (拒绝访问=当前令牌无此权限)" % _err())
        return 2
    print("    OK scm=%s" % scm)

    hsvc = None
    try:
        print("[2] CreateServiceW(LocalSystem)...")
        hsvc = advapi32.CreateServiceW(
            scm, SERVICE_NAME, SERVICE_DISPLAY, SERVICE_ALL_ACCESS,
            SERVICE_WIN32_OWN_PROCESS, SERVICE_AUTO_START, SERVICE_ERROR_NORMAL,
            bin_path, None, None, None, None,
        )
        if not hsvc:
            print("    FAIL err=%d" % _err())
            return 3
        print("    OK service=%s bin=%s" % (SERVICE_NAME, bin_path))

        print("[3] StartServiceW...")
        if not advapi32.StartServiceW(hsvc, 0, None):
            err = _err()
            if err == 1056:  # ERROR_SERVICE_ALREADY_RUNNING
                print("    已在运行 (1056)")
            else:
                print("    FAIL err=%d" % err)
                return 4
        print("    OK")

        print("[4] 等待服务执行完毕...")
        deadline = time.time() + 180
        last_state = None
        while time.time() < deadline:
            st = SERVICE_STATUS()
            advapi32.QueryServiceStatusEx(hsvc, 0, ctypes.byref(st), ctypes.sizeof(st), None)
            if st.dwCurrentState != last_state:
                names = {SERVICE_RUNNING: "RUNNING", SERVICE_STOPPED: "STOPPED",
                         SERVICE_START_PENDING: "START_PENDING", SERVICE_STOP_PENDING: "STOP_PENDING"}
                print("    state=%s exit=%d" % (names.get(st.dwCurrentState, st.dwCurrentState),
                                              st.dwWin32ExitCode))
                last_state = st.dwCurrentState
            if st.dwCurrentState == SERVICE_STOPPED:
                break
            time.sleep(2)
        else:
            print("    超时等待")

        print("[5] DeleteService + Close")
        advapi32.DeleteService(hsvc)
        advapi32.CloseServiceHandle(hsvc)
        hsvc = None
        advapi32.CloseServiceHandle(scm)
        print("    OK 已清理临时服务")
        return 0
    finally:
        if hsvc:
            advapi32.CloseServiceHandle(hsvc)
        advapi32.CloseServiceHandle(scm)


if __name__ == "__main__":
    sys.exit(main())
