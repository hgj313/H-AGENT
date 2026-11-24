# -*- coding: utf-8 -*-
"""保单分析监听 守护进程

守护 policy_analysis.watcher 子进程（崩溃自动拉起 + 指数退避 + 单实例锁）。
与 MQ 直连消费者（erp_feishu_direct_watchdog）完全独立，互不干扰。

使用::

    H-AGENT\\.venv\\Scripts\\python.exe policy_analysis_watchdog.py
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

PYTHON = os.path.join(HERE, "H-AGENT", ".venv", "Scripts", "python.exe")
MODULE = "policy_analysis.watcher"
LOG_PATH = os.path.join(HERE, "policy_analysis_watchdog.log")
LOCK_PATH = os.path.join(HERE, ".policy_analysis_watchdog.lock")
WATCHER_LOG = os.path.join(HERE, "policy_analysis.log")

RESTART_DELAY = 5
MAX_RESTART_DELAY = 300
HEALTH_INTERVAL = 30
HEARTBEAT_TIMEOUT = 900
STARTUP_GRACE = 120


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _pid_alive(pid):
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.restype = ctypes.c_int
        h = kernel32.OpenProcess(0x1000, False, pid)
        if h:
            kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH", "/FO", "CSV"],
            capture_output=True, timeout=15,
        )
        raw = r.stdout or b""
        for enc in ("utf-8", "gb18030"):
            try:
                out = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            out = raw.decode("gb18030", errors="replace")
        return ('"%d"' % pid) in out
    except Exception:
        return False


def _acquire_lock():
    try:
        if os.path.exists(LOCK_PATH):
            try:
                old = int(open(LOCK_PATH, "r", encoding="utf-8").read().strip())
            except Exception:
                old = None
            if old and _pid_alive(old) and old != os.getpid():
                log(f"单实例锁冲突：已有 watchdog (PID {old})，本进程退出。")
                return False
        with open(LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log(f"锁写入失败（忽略继续）: {e}")
        return True


def _release_lock():
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def _safe_kill(proc):
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
            return
        except Exception:
            pass
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _heartbeat_age():
    try:
        if not os.path.exists(WATCHER_LOG):
            return None
        return time.time() - os.path.getmtime(WATCHER_LOG)
    except Exception:
        return None


def main():
    if not _acquire_lock():
        return
    log("=" * 60)
    log("保单分析监听 watchdog 启动")
    log(f"被守护模块: -m {MODULE}")
    log("=" * 60)

    if not os.path.exists(PYTHON):
        log(f"找不到解释器: {PYTHON}")
        return

    delay = RESTART_DELAY
    try:
        while True:
            log(f"启动保单分析监听 (python -m {MODULE}) ...")
            try:
                log_file = open(LOG_PATH, "a", encoding="utf-8")
                proc = subprocess.Popen(
                    [PYTHON, "-u", "-m", MODULE],
                    cwd=HERE,
                    stdout=log_file,
                    stderr=log_file,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                log_file.close()
            except Exception as e:
                log(f"启动异常: {e}，{delay}s 后重试...")
                time.sleep(delay)
                delay = min(delay * 2, MAX_RESTART_DELAY)
                continue

            log(f"监听进程已启动: PID {proc.pid}")
            started_at = time.time()

            while True:
                rc = proc.poll()
                if rc is not None:
                    log(f"监听进程退出（码 {rc}），{delay}s 后重启...")
                    break
                if time.time() - started_at > STARTUP_GRACE:
                    age = _heartbeat_age()
                    if age is not None and age > HEARTBEAT_TIMEOUT:
                        log(f"心跳超时（{int(age)}s），判定假死，重启...")
                        _safe_kill(proc)
                        break
                time.sleep(HEALTH_INTERVAL)

            time.sleep(delay)
            delay = min(delay * 2, MAX_RESTART_DELAY)
    except KeyboardInterrupt:
        log("watchdog 退出")
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
