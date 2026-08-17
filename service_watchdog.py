"""保险单识别系统 - 守护进程（watchdog）

崩溃自动重启服务，保证 8765 端口服务持续可用。
配合 Windows 任务计划程序开机自启（用 pythonw.exe 隐藏窗口运行）。

使用：
    通过任务计划程序调用 pythonw.exe service_watchdog.py
"""

import subprocess
import sys
import time

PYTHON = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
SERVER_SCRIPT = r"web_app\server.py"
WORKDIR = r"C:\insurance-automation"
RESTART_DELAY = 3  # 崩溃后重启延迟（秒）


def log(msg: str):
    print(f"[watchdog {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    log("watchdog 启动，监控保险单识别系统服务...")
    while True:
        log("启动服务...")
        try:
            proc = subprocess.Popen([PYTHON, SERVER_SCRIPT], cwd=WORKDIR)
            proc.wait()
            code = proc.returncode
            log(f"服务退出（退出码 {code}），{RESTART_DELAY} 秒后重启...")
        except Exception as e:
            log(f"启动异常: {e}，{RESTART_DELAY} 秒后重试...")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
