# -*- coding: utf-8 -*-
"""提权后拉起「保单分析监听」守护（Session 0 常驻）

本机 `ConsentPromptBehaviorAdmin=0` → 管理员账户提权**不弹 UAC 提示**，静默提升到 High。

流程：
  1. 未提升 → ShellExecuteW("runas") 静默重启自身，本进程退出
  2. 已提升 → 通过 SCM 创建临时 LocalSystem 服务执行 _sys_stage2.py
     → 以 SYSTEM 身份拉起 policy_analysis_watchdog.py（Session 0 常驻）

所有输出写入 _elevated_stage2.log（提权进程没有可用控制台）。
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

REPO = r"C:\insurance-automation"
LOG = os.path.join(REPO, "_elevated_stage2.log")
RESULT = os.path.join(REPO, "_elevated_stage2_result.json")
STAGE2 = os.path.join(REPO, "_sys_stage2.py")
PY_EXE = os.path.join(REPO, "H-AGENT", ".venv", "Scripts", "python.exe")

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.ShellExecuteW.restype = wintypes.HINSTANCE
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]


def is_elevated():
    """IsUserAnAdmin 对未提升的管理员令牌返回 False（Administrators SID 为 Deny-only）"""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    if not is_elevated():
        log("当前非提升令牌，发起静默提权（不弹 UAC）...")
        ret = shell32.ShellExecuteW(
            None, "runas", PY_EXE, '"%s"' % os.path.abspath(__file__), None, 0)
        log("ShellExecuteW(runas) ret=%d" % ret)
        if ret <= 32:
            log("提权失败：请手动以管理员身份运行本脚本")
        return 0

    log("=" * 60)
    log("提权执行器启动（已提升）")

    try:
        sys.path.insert(0, REPO)
        import _run_sys_task
        logf = open(LOG, "a", encoding="utf-8", buffering=1)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf
        try:
            sys.argv = ["_run_sys_task.py", STAGE2]
            rc = _run_sys_task.main()
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            logf.flush()
            logf.close()
        log("_run_sys_task 退出码=%s" % rc)
    except Exception as e:
        log("_run_sys_task 异常: %r" % (e,))

    time.sleep(2)
    stage2 = {}
    p2 = os.path.join(REPO, "_sys_stage2_result.json")
    if os.path.exists(p2):
        try:
            with open(p2, "r", encoding="utf-8") as f:
                stage2 = json.load(f)
        except Exception as e:
            stage2 = {"error": str(e)}
    log("stage2 结果: %s" % json.dumps(stage2, ensure_ascii=False))

    try:
        with open(RESULT, "w", encoding="utf-8") as f:
            json.dump({"finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "elevated": True, "stage2": stage2}, f,
                      ensure_ascii=False, indent=2)
    except Exception as e:
        log("结果写入失败: %r" % (e,))

    log("提权执行器结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
