# -*- coding: utf-8 -*-
"""用 ctypes ShellExecuteW("runas") 静默提权启动 _elevated_run.py

本机 ConsentPromptBehaviorAdmin=0 → 管理员账户提权不弹 UAC 提示。
返回 <=32 表示启动失败。
"""

import ctypes
import sys
from ctypes import wintypes

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.ShellExecuteW.restype = wintypes.HINSTANCE
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]

PY = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
TARGET = r"C:\insurance-automation\_elevated_run.py"


def main():
    args = '"%s"' % TARGET
    ret = shell32.ShellExecuteW(None, "runas", PY, args, None, 0)
    print("ShellExecuteW(runas) ret=%d err=%d" % (ret, ctypes.get_last_error()))
    if ret <= 32:
        print("FAIL: ShellExecuteW=%d" % ret)
        return 1
    print("OK: 提权进程已启动 (pid=%d)" % ret)
    return 0


if __name__ == "__main__":
    sys.exit(main())
