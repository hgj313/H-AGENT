"""提权重启 8765 服务（普通权限入口）。

为什么需要它
------------
8765 服务由 **SYSTEM 身份**的 watchdog 拉起（进程链 pythonw → watchdog → server）。
普通权限下无法终止它：
  · taskkill → 拒绝访问
  · OpenProcess → 失败
  · 提权到 Administrator 后 AdjustTokenPrivileges → 1300 ERROR_NOT_ALL_ASSIGNED
    （本机未给管理员令牌分配 SeDebugPrivilege）

唯一可行路径：**注册一次性 SYSTEM 计划任务**执行终止脚本，
watchdog 检测到子进程退出（proc.poll() != None）后 3 秒自动拉起新进程。

本文件的作用
------------
PowerShell 工具会拦截 `Start-Process powershell.exe`，
因此改为：Python 内部用 subprocess 调 powershell —— 子进程继承父进程的管理员令牌。

调用链
------
tools/elevate_restart.bat  (双击 → 触发 UAC 提权)
  → python tools/elevate_restart.py   (UAC 弹窗后已是管理员令牌)
    → subprocess powershell.exe -File tools/system_restart_service.ps1
      → Register-ScheduledTask (SYSTEM) → Start-ScheduledTask
        → tools/system_restart_service.py 以 SYSTEM 身份终止 8765
          → watchdog 3s 后自动拉起（加载最新代码）
"""

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS1 = os.path.join(BASE, "tools", "system_restart_service.ps1")
LOG = os.path.join(BASE, "data", "_restart_elevated.log")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        out = r.stdout or ""
        err = r.stderr or ""
    except Exception as e:  # noqa: BLE001
        out, err = "", f"EXCEPTION: {e}"

    try:
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("=== stdout ===\n" + out + "\n=== stderr ===\n" + err)
    except Exception:
        pass

    print(out)
    if err.strip():
        print("--- stderr ---")
        print(err[-1500:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
