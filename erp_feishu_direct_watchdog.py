# -*- coding: utf-8 -*-
"""
ERP → 飞书「今日打卡数据」直连消费者 守护进程

背景
----
直连消费者 (``erp_feishu_direct.consumer``) 是独立进程，不依赖 8765 服务。
它挂在 MQ 上做实时同步，一旦进程死掉，飞书表就停止更新 —— 而表里的数据
是给人看「今天谁打卡了」，停了会直接影响现场管理。

为什么不用 service_watchdog.py
------------------------------
8765 的 service_watchdog.py 以 SYSTEM 权限运行，且它的生命周期与 8765 服务绑定。
直连消费者是**另一条链路**（用户已明确本地保险管理AI助手不再参与这条数据流），
不应该被 8765 的重启带起带落。因此独立守护。

职责
----
1. 启动并守护 ``erp_feishu_direct.consumer`` 子进程（崩溃自动拉起）
2. 指数退避重启：配置未就绪（例如 RocketMQ 消费组还没在控制台建）时，
   不会每 5 秒刷一次屏，而是逐步退避到最多 5 分钟一次
3. 心跳假死检测：消费者每 5 分钟往日志写一次心跳，用日志文件 mtime 判定
4. 单实例锁：防止重复启动多个 watchdog

使用::

    H-AGENT\\.venv\\Scripts\\python.exe erp_feishu_direct_watchdog.py
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 必须用带 mq_http_sdk 的解释器
PYTHON = os.path.join(HERE, "H-AGENT", ".venv", "Scripts", "python.exe")
MODULE = "erp_feishu_direct.consumer"
LOG_PATH = os.path.join(HERE, "erp_feishu_direct_watchdog.log")
LOCK_PATH = os.path.join(HERE, ".erp_feishu_direct_watchdog.lock")
# 消费者自己的轮转日志（心跳写在这里）
CONSUMER_LOG = os.path.join(HERE, "erp_feishu_direct.log")

RESTART_DELAY = 5          # 首次崩溃后的重启延迟（秒）
MAX_RESTART_DELAY = 300    # 指数退避上限（秒）
HEALTH_INTERVAL = 30        # 每隔多久检查一次（秒）
HEARTBEAT_TIMEOUT = 900    # 消费者心跳 300s 一次，留 3 倍容忍
STARTUP_GRACE = 120        # 启动后宽限期（秒），期内不做心跳判定


def log(msg):
    """写文件日志（pythonw 下 stdout 不可用，必须写文件）"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _pid_alive(pid):
    """检测 PID 是否存活。

    注意：直接 OpenProcess 对 **Session 0 / SYSTEM 进程** 会因 DACL 失败（err=5），
    Medium 完整性级别下拿不到 PROCESS_QUERY_LIMITED_INFORMATION → 会误判「已死」，
    导致本该生效的单实例锁失效、重复起消费者。
    因此失败时用 tasklist 兜底（进程表全局可见，跨会话可靠）。
    """
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    # 兜底：tasklist 的进程表跨会话可见
    try:
        import subprocess
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


def _acquire_singleton_lock():
    """获取单实例锁。已有活着的 watchdog 则退出。"""
    try:
        if os.path.exists(LOCK_PATH):
            try:
                old_pid = int(open(LOCK_PATH, "r", encoding="utf-8").read().strip())
            except Exception:
                old_pid = None
            if old_pid and _pid_alive(old_pid) and old_pid != os.getpid():
                log(f"单实例锁冲突：已有 watchdog 在运行 (PID {old_pid})，本进程退出。")
                return False
        with open(LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log(f"单实例锁写入失败（忽略，继续运行）: {e}")
        return True


def _release_singleton_lock():
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def _heartbeat_age():
    """消费者日志文件距今多少秒没更新；读不到返回 None"""
    try:
        if not os.path.exists(CONSUMER_LOG):
            return None
        return time.time() - os.path.getmtime(CONSUMER_LOG)
    except Exception:
        return None


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


def main():
    if not _acquire_singleton_lock():
        return

    log("=" * 60)
    log("ERP→飞书直连消费者 watchdog 启动")
    log(f"解释器: {PYTHON}")
    log(f"被守护模块: -m {MODULE}")
    log(f"心跳超时阈值: {HEARTBEAT_TIMEOUT}s")
    log("=" * 60)

    if not os.path.exists(PYTHON):
        log(f"❌ 找不到解释器: {PYTHON}")
        return

    delay = RESTART_DELAY
    try:
        while True:
            log(f"启动消费者 (python -m {MODULE}) ...")
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
                log(f"启动异常: {e}，{delay} 秒后重试...")
                time.sleep(delay)
                delay = min(delay * 2, MAX_RESTART_DELAY)
                continue

            log(f"消费者已启动: PID {proc.pid}")
            started_at = time.time()

            while True:
                rc = proc.poll()
                if rc is not None:
                    log(f"消费者退出（退出码 {rc}），{delay} 秒后重启...")
                    break

                # 心跳假死检测
                if time.time() - started_at > STARTUP_GRACE:
                    age = _heartbeat_age()
                    if age is not None and age > HEARTBEAT_TIMEOUT:
                        log(f"心跳超时（{int(age)}s 未更新 > {HEARTBEAT_TIMEOUT}s），判定假死，强杀重启...")
                        _safe_kill(proc)
                        break
                time.sleep(HEALTH_INTERVAL)

            time.sleep(delay)
            # 指数退避：配置类错误（消费组未建等）不至于刷屏
            delay = min(delay * 2, MAX_RESTART_DELAY)
    except KeyboardInterrupt:
        log("watchdog 退出")
    finally:
        _release_singleton_lock()


if __name__ == "__main__":
    main()
