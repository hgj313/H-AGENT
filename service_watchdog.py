"""保险管理AI助手 - 守护进程（watchdog）

崩溃自动重启服务，保证 8765 端口服务持续可用。
用文件日志记录（避免 pythonw 无 stdout 的问题）。

使用：
    pythonw.exe service_watchdog.py   （无窗口后台运行）
"""

import subprocess
import sys
import time
import os
import socket

PYTHON = r"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe"
SERVER_SCRIPT = r"web_app\server.py"
WORKDIR = r"C:\insurance-automation"
LOG_PATH = r"C:\insurance-automation\watchdog.log"
RESTART_DELAY = 3  # 崩溃后重启延迟（秒）
LOCK_PATH = r"C:\insurance-automation\.watchdog.lock"  # 单实例锁（防多会话重复启动抢端口）

# ---- MQ bridge 联动配置（与 8765 服务生命周期绑定）----
BRIDGE_SCRIPT = r"insurance_agent\tools\mq_punch_bridge.py"
BRIDGE_LOG_PATH = r"C:\insurance-automation\mq_bridge_stderr.log"
BRIDGE_RESTART_DELAY = 5  # bridge 崩溃后多久重启（秒）

# 健康检查：不仅检测进程是否退出，还检测服务是否「假死」（端口在但接口无响应）
HEALTH_URL = "http://127.0.0.1:8765/api/health"
HEALTH_INTERVAL = 15    # 运行中每隔多少秒做一次健康检查（秒）
HEALTH_TIMEOUT = 5      # 单次健康检查超时（秒）
STARTUP_GRACE = 20      # 启动后宽限期，宽限内只检测崩溃、不做健康检查（避免误杀尚未就绪的服务）


def _acquire_singleton_lock() -> bool:
    """获取单实例锁。若已有存活的 watchdog，则退出（返回 False）。

    已存在的锁若指向已死亡的 PID，则接管（覆盖）。
    """
    try:
        if os.path.exists(LOCK_PATH):
            try:
                old_pid = int(open(LOCK_PATH, "r", encoding="utf-8").read().strip())
            except Exception:
                old_pid = None
            if old_pid:
                try:
                    import ctypes
                    # 0 = PROCESS_QUERY_LIMITED_INFORMATION
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(0x1000, False, old_pid)
                    if handle:
                        kernel32.CloseHandle(handle)
                        log(f"单实例锁冲突：已有存活的 watchdog (PID {old_pid})，本进程退出。")
                        return False
                except Exception:
                    pass  # 进程不存在 -> 接管
        with open(LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log(f"单实例锁写入失败（忽略）: {e}")
    return True


def _release_singleton_lock():
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def _port_in_use(port: int = 8765) -> bool:
    """检测端口是否已被占用（已有实例在提供服务）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _try_acquire_server_lock():
    """原子获取服务启动锁（O_EXCL）。成功返回文件描述符，失败返回 None。

    O_EXCL 为 OS 级原子创建：无论 venv 还是 uv 启动的 watchdog，
    全局只有一个进程能成功创建锁文件，从而只有它能启动 server，
    彻底杜绝双实例抢 8765 端口。

    若锁文件已存在但指向的 PID 已死亡（上次被强杀遗留），则清理后重试，
    避免失效锁导致永远无法启动。
    """
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        return fd
    except FileExistsError:
        # 锁已存在。检查持有者：
        #   ① PID 不存在（已死）→ 失效锁，清理后重试；
        #   ② PID 存在但不是 python 进程（Windows PID 复用）→ 失效锁，清理后重试；
        #   ③ PID 存在且是 python 进程 → 真占有者，本次让出（返回 None）。
        try:
            old_pid = int(open(LOCK_PATH, "r", encoding="utf-8").read().strip())
            if not old_pid:
                raise ValueError("empty pid")
            if not _pid_alive(old_pid):
                log(f"服务锁指向死亡 PID {old_pid}，清理后重试...")
            elif not _pid_is_python(old_pid):
                log(f"服务锁指向 PID {old_pid} 但它不是 python 进程（PID 复用？），清理后重试...")
            else:
                # 真占有者
                return None
            os.remove(LOCK_PATH)
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            return fd
        except Exception as e:
            log(f"服务锁处理异常: {e}")
            return None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def _pid_is_python(pid: int) -> bool:
    """PID 活着时，进一步确认它是 python.exe/pythonw.exe 进程。

    防止 Windows PID 复用：锁文件里的旧 PID 可能被系统或其他程序
    重新分配给一个完全无关的进程，此时仅 _pid_alive 会误判"还活着"。
    """
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            buf = ctypes.create_unicode_buffer(512)
            sz = ctypes.c_uint(ctypes.sizeof(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(sz)):
                img = buf.value.lower()
                return img.endswith("\\python.exe") or img.endswith("\\pythonw.exe")
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _health_ok() -> bool:
    """访问 /api/health 判断服务是否真的可用（而非仅端口被占用）。

    返回 False 表示服务假死或无响应，应触发重启。
    注意：若 requests 不可用则保守返回 True（不误杀）。
    """
    try:
        import requests
    except Exception:
        return True
    try:
        r = requests.get(HEALTH_URL, timeout=HEALTH_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _safe_kill(proc):
    """安全地强杀子进程（用于假死重启）。"""
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


# ============ MQ bridge 联动 ============

def _start_bridge():
    """启动 MQ bridge 子进程。返回 Popen 对象或 None。

    bridge 自带 8767 单实例锁：若锁被其他实例占用，bridge 会自行 exit(2)，
    watchdog 会在下一轮监督循环里发现它已退出并自动重启（确保最终只有一个）。
    """
    try:
        log_path = os.path.join(WORKDIR, "mq_bridge_stdout.log")
        log_file = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [PYTHON, BRIDGE_SCRIPT],
            cwd=WORKDIR,
            stdout=log_file,
            stderr=log_file,  # bridge 自身的 logger 也写 mq_bridge_stderr.log，这里只兜底
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        log(f"bridge 已启动: PID {proc.pid}")
        return proc
    except Exception as e:
        log(f"bridge 启动异常: {e}")
        return None


def _kill_bridge(proc):
    """安全关闭 bridge 子进程。terminate（5s）→ kill（3s）两级降级。"""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
            log(f"bridge 已 graceful 终止: PID {proc.pid}")
            return
        except subprocess.TimeoutExpired:
            pass
        # graceful 超时 → 强杀
        proc.kill()
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
        log(f"bridge 已强杀: PID {proc.pid}")
    except Exception as e:
        log(f"kill bridge 异常: {e}")


def _venv_watchdog_alive() -> bool:
    """是否存在存活的 venv 版 watchdog（本机优先实例）。"""
    try:
        venv_py = "H-AGENT\\.venv\\Scripts\\python.exe"
        procs = subprocess.run(
            ["wmic", "process", "where",
             f"name='python.exe' and commandline like '%service_watchdog%' and commandline like '%{venv_py}%'",
             "get", "processid"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in procs.splitlines():
            line = line.strip()
            if line.isdigit():
                if _pid_alive(int(line)) and int(line) != os.getpid():
                    return True
    except Exception:
        pass
    return False


def _self_yield_to_venv() -> bool:
    """若本进程以非 venv 的 python（如 uv）运行，且已有 venv watchdog 存活，则让出。

    返回 True 表示应退出（由 venv 实例主导）。
    """
    exe = sys.executable.replace("/", "\\").lower()
    if "h-agent\\.venv\\scripts\\python.exe" in exe:
        return False  # 本身就是 venv，主导
    # 非 venv（uv 等）：若 venv watchdog 已存活，则退出让出
    if _venv_watchdog_alive():
        log("检测到 venv 版 watchdog 已运行，本（非 venv）实例退出让出。")
        return True
    return False


def _release_server_lock(fd):
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def log(msg: str):
    """写文件日志（pythonw 下 stdout 不可用，必须写文件）"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def main():
    if _self_yield_to_venv():
        return
    log("=== watchdog 启动，监控保险管理AI助手服务 + MQ bridge（生命周期联动）===")
    bridge_proc = None  # type: subprocess.Popen | None
    while True:
        # 原子锁：仅成功创建锁文件的 watchdog 持有「服务启动权」。
        # 一次性获取并持有整个 server 生命周期，避免两个 watchdog（venv/uv）
        # 反复抢锁造成崩溃循环；另一实例仅休眠等待故障转移。
        lock_fd = _try_acquire_server_lock()
        if lock_fd is None:
            time.sleep(RESTART_DELAY)
            continue
        try:
            while True:
                # 端口已被其他实例（含 agent 直接拉起的 uv server）占用时，
                # 不重复派生必败的 server，仅休眠等待故障转移，避免孤儿进程与崩溃循环。
                if _port_in_use(8765):
                    time.sleep(RESTART_DELAY)
                    continue
                log("启动服务...")
                try:
                    # 服务日志重定向到文件，便于排查（pythonw 无 stdout）
                    log_file = open(os.path.join(WORKDIR, "server.log"), "a", encoding="utf-8")
                    err_file = open(os.path.join(WORKDIR, "server.err.log"), "a", encoding="utf-8")
                    proc = subprocess.Popen(
                        [PYTHON, SERVER_SCRIPT],
                        cwd=WORKDIR,
                        stdout=log_file,
                        stderr=err_file,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                    log_file.close()
                    err_file.close()
                except Exception as e:
                    log(f"启动异常: {e}，{RESTART_DELAY} 秒后重试...")
                    time.sleep(RESTART_DELAY)
                    continue

                # ---- 联动启动 bridge（与 8765 服务生命周期绑定）----
                # bridge 自身带 8767 单实例锁：若旧 bridge 还活着会立即退出，
                # 所以这里先 kill 一次再启，确保旧实例不影响新启动顺序。
                if bridge_proc is not None:
                    _kill_bridge(bridge_proc)
                    bridge_proc = None
                time.sleep(BRIDGE_RESTART_DELAY)  # 等服务端口稳定
                bridge_proc = _start_bridge()

                # 监督循环：崩溃 + 假死 双检测（同时监督 server + bridge）
                started_at = time.time()
                while True:
                    # 1) 服务崩溃检测
                    rc = proc.poll()  # None 表示仍在运行
                    if rc is not None:
                        log(f"服务退出（退出码 {rc}），{RESTART_DELAY} 秒后重启...")
                        # 服务退出会导致 bridge 转发失败 → 同步关闭 bridge
                        if bridge_proc is not None:
                            _kill_bridge(bridge_proc)
                            bridge_proc = None
                        break
                    # 2) bridge 崩溃检测（不查假死：bridge 是 I/O 密集型，没有 HTTP 接口可探活）
                    if bridge_proc is not None:
                        br_rc = bridge_proc.poll()
                        if br_rc is not None:
                            log(f"bridge 异常退出（退出码 {br_rc}），{BRIDGE_RESTART_DELAY} 秒后重启 bridge...")
                            bridge_proc = _start_bridge()
                    # 3) 服务健康检查（宽限期后启用）
                    if time.time() - started_at > STARTUP_GRACE and not _health_ok():
                        log("服务健康检查失败（可能假死），强制重启...")
                        _safe_kill(proc)
                        # 同步关闭 bridge（与服务同生命周期）
                        if bridge_proc is not None:
                            _kill_bridge(bridge_proc)
                            bridge_proc = None
                        break
                    time.sleep(HEALTH_INTERVAL)
                time.sleep(RESTART_DELAY)
        finally:
            # watchdog 关闭（finally）→ 同步关闭 bridge，保持生命周期对齐
            if bridge_proc is not None:
                _kill_bridge(bridge_proc)
                bridge_proc = None
            _release_server_lock(lock_fd)


if __name__ == "__main__":
    main()
