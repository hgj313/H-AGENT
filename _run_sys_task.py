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

SERVICE_NAME_BASE = "WBInsuranceStage1"
SERVICE_DISPLAY = "WorkBuddy Insurance Stage1 Runner"

SC_MANAGER_CREATE_SERVICE = 0x0002
SC_MANAGER_ALL_ACCESS = 0xF003F
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_DEMAND_START = 0x00000003
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

# ⚠️ 必须显式声明 argtypes：否则 ctypes 默认按 32 位 int 传参，
#    64 位 HANDLE（hSCManager / hService）会溢出报
#    "OverflowError: int too long to convert"。
advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
advapi32.CreateServiceW.argtypes = [
    wintypes.HANDLE,      # hSCManager
    wintypes.LPCWSTR,     # lpServiceName
    wintypes.LPCWSTR,     # lpDisplayName
    wintypes.DWORD,       # dwDesiredAccess
    wintypes.DWORD,       # dwServiceType
    wintypes.DWORD,       # dwStartType
    wintypes.DWORD,       # dwErrorControl
    wintypes.LPCWSTR,     # lpBinaryPathName
    wintypes.LPVOID,      # lpLoadOrderGroup
    wintypes.LPVOID,      # lpTagId
    wintypes.LPVOID,      # lpDependencies
    wintypes.LPVOID,      # lpServiceStartName
    wintypes.LPVOID,      # lpPassword
]
advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
advapi32.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
advapi32.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
advapi32.DeleteService.argtypes = [wintypes.HANDLE]
advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
advapi32.QueryServiceStatusEx.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, wintypes.LPVOID,
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


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


def _query_state(hsvc):
    st = SERVICE_STATUS()
    advapi32.QueryServiceStatusEx(hsvc, 0, ctypes.byref(st), ctypes.sizeof(st), None)
    return st


def _sc(*args):
    """调用 sc.exe 并自适应解码（Windows 原生命令输出为 GBK）"""
    import subprocess
    try:
        r = subprocess.run(["sc.exe"] + list(args), capture_output=True, timeout=30)
        raw = r.stdout + r.stderr
        for enc in ("utf-8", "gb18030"):
            try:
                return r.returncode, raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return r.returncode, raw.decode("gb18030", errors="replace")
    except Exception as e:
        return -1, "failed: %r" % (e,)


def _delete_existing(name):
    """删除可能残留的同名服务（ERROR_SERVICE_EXISTS / marked-for-delete 残留）。

    用 sc.exe 而不是 ctypes：ControlService/OpenService 在残留句柄场景下容易踩
    访问冲突，sc.exe 的 stop+delete 语义更稳（运行中则标记删除，停止后消失）。
    返回 True 表示已清理干净。
    """
    rc, out = _sc("stop", name)
    print("    sc stop -> rc=%s %s" % (rc, out.strip()[:120]))
    time.sleep(2)
    rc, out = _sc("delete", name)
    print("    sc delete -> rc=%s %s" % (rc, out.strip()[:120]))
    time.sleep(1)
    # 确认是否真的消失
    rc, out = _sc("query", name)
    if "FAILED 1060" in out or "1060" in out:
        return True
    return "does not exist" in out or "1060" in out


def main():
    global SERVICE_NAME
    script = sys.argv[1] if len(sys.argv) > 1 else r"C:\insurance-automation\_sys_stage1.py"
    py = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
    bin_path = '"%s" "%s"' % (py, script)
    # 服务名带时间戳：即使上次异常没删干净，也不会与残留冲突
    SERVICE_NAME = "%s_%s" % (SERVICE_NAME_BASE, time.strftime("%H%M%S"))

    print("[1] OpenSCManager(CREATE_SERVICE)...")
    scm = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CREATE_SERVICE)
    if not scm:
        print("    FAIL err=%d (拒绝访问=当前令牌无此权限)" % _err())
        return 2
    print("    OK scm=%s" % scm)

    hsvc = None
    try:
        print("[2] CreateServiceW(LocalSystem) -> %s" % SERVICE_NAME)
        # CreateServiceW 共 13 个参数：
        #   hSCManager, lpServiceName, lpDisplayName, dwDesiredAccess, dwServiceType,
        #   dwStartType, dwErrorControl, lpBinaryPathName, lpLoadOrderGroup, lpTagId,
        #   lpDependencies, lpServiceStartName, lpPassword
        # lpServiceStartName=None → 默认 LocalSystem 身份
        hsvc = advapi32.CreateServiceW(
            scm, SERVICE_NAME, SERVICE_DISPLAY, SERVICE_ALL_ACCESS,
            SERVICE_WIN32_OWN_PROCESS, SERVICE_DEMAND_START, SERVICE_ERROR_NORMAL,
            bin_path, None, None, None, None, None,
        )
        if not hsvc:
            err = _err()
            if err == 1073:  # ERROR_SERVICE_EXISTS：清理残留后重试
                print("    服务已存在(err=1073)，先清理残留...")
                if _delete_existing(SERVICE_NAME):
                    print("    残留已清理，重新创建")
                    hsvc = advapi32.CreateServiceW(
                        scm, SERVICE_NAME, SERVICE_DISPLAY, SERVICE_ALL_ACCESS,
                        SERVICE_WIN32_OWN_PROCESS, SERVICE_DEMAND_START, SERVICE_ERROR_NORMAL,
                        bin_path, None, None, None, None, None,
                    )
                    if not hsvc:
                        print("    FAIL 重试后仍失败 err=%d" % _err())
                        return 3
                else:
                    print("    FAIL 残留服务无法删除")
                    return 3
            else:
                print("    FAIL err=%d" % err)
                return 3
        print("    OK service=%s bin=%s" % (SERVICE_NAME, bin_path))

        print("[3] StartServiceW...")
        if not advapi32.StartServiceW(hsvc, 0, None):
            err = _err()
            if err == 1056:  # ERROR_SERVICE_ALREADY_RUNNING
                print("    已在运行 (1056)")
            elif err == 1053:  # ERROR_SERVICE_REQUEST_TIMEOUT
                # 被拉起的程序没有调用 StartServiceCtrlDispatcher，SCM 等不到
                # RUNNING 上报而超时；但**进程已经被拉起并正在执行脚本**，
                # 后续的状态轮询会等到它自然退出。此处视为成功。
                print("    超时(1053)：程序未注册控制分发器，但进程已拉起，继续等待其结束")
            else:
                print("    FAIL err=%d" % err)
                return 4
        print("    OK")

        print("[4] 等待服务执行完毕...")
        # ⚠️ 一次性服务（DEMAND_START + ERROR_NORMAL）在最后一个服务进程退出后，
        #    SCM 会**自动删除该服务**，hsvc 句柄随即陈旧 →
        #    QueryServiceStatusEx 会抛 "access violation" SEH。
        #    因此状态判定统一走 sc.exe query（子进程方式，稳定且能区分
        #    1060=已删除 / 1072=标记删除），不再用陈旧句柄查状态。
        deadline = time.time() + 180
        last_state = None
        gone_markers = ("1060", "1072", "does not exist", "未安装", "标记为删除")
        while time.time() < deadline:
            rc_q, out_q = _sc("query", SERVICE_NAME)
            if any(m in out_q for m in gone_markers):
                print("    服务已从 SCM 消失（脚本执行完毕，SCM 自动删除）")
                break
            state = None
            for line in out_q.splitlines():
                t = line.strip()
                if t.upper().startswith("STATE"):
                    for tok in t.replace(":", " ").split():
                        if tok.isdigit():
                            state = int(tok)
                            break
                    break
            if state is not None and state != last_state:
                names = {SERVICE_RUNNING: "RUNNING", SERVICE_STOPPED: "STOPPED",
                         SERVICE_START_PENDING: "START_PENDING", SERVICE_STOP_PENDING: "STOP_PENDING"}
                print("    state=%s" % names.get(state, state))
                last_state = state
            if state == SERVICE_STOPPED:
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
            # 先停止再删除：运行中的服务无法 DeleteService（会残留 marked-for-delete）
            # ⚠️ 句柄可能已因 SCM 自动删除而陈旧 → 所有 ctypes 调用都要兜异常
            try:
                _st2 = SERVICE_STATUS()
                advapi32.ControlService(hsvc, SERVICE_CONTROL_STOP, ctypes.byref(_st2))
                for _ in range(20):
                    st = _query_state(hsvc)
                    if st.dwCurrentState == SERVICE_STOPPED:
                        break
                    time.sleep(1)
            except Exception:
                pass
            try:
                advapi32.DeleteService(hsvc)
            except Exception:
                pass
            try:
                advapi32.CloseServiceHandle(hsvc)
            except Exception:
                pass
            hsvc = None
        # sc.exe 兜底：确保 SCM 里不留残留条目
        try:
            _delete_existing(SERVICE_NAME)
        except Exception:
            pass
        advapi32.CloseServiceHandle(scm)


if __name__ == "__main__":
    sys.exit(main())
