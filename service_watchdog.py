"""保险单识别系统 - 守护进程（watchdog）

崩溃自动重启服务，保证 8765 端口服务持续可用。
用文件日志记录（避免 pythonw 无 stdout 的问题）。

使用：
    pythonw.exe service_watchdog.py   （无窗口后台运行）
"""

import subprocess
import sys
import time
import os

PYTHON = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
SERVER_SCRIPT = r"web_app\server.py"
WORKDIR = r"C:\insurance-automation"
LOG_PATH = r"C:\insurance-automation\watchdog.log"
RESTART_DELAY = 3  # 崩溃后重启延迟（秒）


def log(msg: str):
    """写文件日志（pythonw 下 stdout 不可用，必须写文件）"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def main():
    log("=== watchdog 启动，监控保险单识别系统服务 ===")
    while True:
        log("启动服务...")
        try:
            # 用 DETACHED 标志，让子进程尽量脱离
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                [PYTHON, SERVER_SCRIPT],
                cwd=WORKDIR,
                creationflags=creationflags,
            )
            proc.wait()
            code = proc.returncode
            log(f"服务退出（退出码 {code}），{RESTART_DELAY} 秒后重启...")
        except Exception as e:
            log(f"启动异常: {e}，{RESTART_DELAY} 秒后重试...")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
