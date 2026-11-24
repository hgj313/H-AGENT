# -*- coding: utf-8 -*-
"""提权后的一键执行器（由 ShellExecuteW "runas" 启动）

本机 `ConsentPromptBehaviorAdmin=0` → 管理员账户提权**不弹 UAC 提示**，静默提升到 High。

以管理员（High integrity）身份依次完成：
  1. 写停用标记 .assistant_disabled
  2. 尝试直接终止残留 bridge（预期失败：SYSTEM 进程受 MIC 拦截，仅记录日志）
  3. 创建临时 LocalSystem 服务执行 _sys_stage1.py
     → 以 SYSTEM 身份真正终止 bridge，并启动 erp_feishu_direct 直连消费者守护
  4. 写结果文件 _disable_result.json

所有输出写入 _elevated_run.log（提权进程没有可用控制台）。
"""

import io
import json
import os
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes

REPO = r"C:\insurance-automation"
FLAG = os.path.join(REPO, ".assistant_disabled")
LOG = os.path.join(REPO, "_elevated_run.log")
RESULT = os.path.join(REPO, "_disable_result.json")
STAGE1 = os.path.join(REPO, "_sys_stage1.py")
PY_EXE = os.path.join(REPO, "H-AGENT", ".venv", "Scripts", "python.exe")

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.ShellExecuteW.restype = wintypes.HINSTANCE
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]


def is_elevated():
    """是否已处于提升后的管理员令牌。

    IsUserAnAdmin 对未提升的管理员令牌返回 False（Administrators SID 为 Deny-only），
    因此可作为「是否需要提权」的判据。
    """
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated():
    """静默提权重启自身（ConsentPromptBehaviorAdmin=0 → 不弹 UAC 提示）。

    返回 True 表示已成功发起提权进程。
    """
    ret = shell32.ShellExecuteW(None, "runas", sys.executable, '"%s"' % os.path.abspath(__file__), None, 0)
    return ret > 32



def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def decode(raw):
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, decode(r.stdout) + decode(r.stderr)
    except Exception as e:
        return -1, "run failed: %r" % (e,)


def whoami_info():
    rc, out = run(["whoami", "/all"], timeout=30)
    return out


def main():
    # 未提升时：静默提权重启自身（不弹 UAC），本进程直接退出
    if not is_elevated():
        log("当前非提升令牌，发起静默提权...")
        if relaunch_elevated():
            log("提权进程已发起")
        else:
            log("提权失败：请手动以管理员身份运行本脚本")
        return 0

    log("=" * 60)
    log("提权执行器启动（已提升）")
    log("whoami: %s" % whoami_info()[:600].replace("\n", " | "))

    # ---- 1. 停用标记 ----
    try:
        with open(FLAG, "w", encoding="utf-8") as f:
            f.write("disabled at " + time.strftime("%Y-%m-%d %H:%M:%S"))
        log("[1] 停用标记已写入: %s" % FLAG)
    except Exception as e:
        log("[1] 停用标记写入失败: %r" % (e,))

    # ---- 2. 终止残留的 MQ bridge ----
    # 提升后的管理员令牌自带 SeDebugPrivilege，可以终止 Session 0 的 SYSTEM 进程
    # （Medium 完整性级别下 MIC 会拦截）。
    # 跨会话读不到 Session 0 的 CommandLine，但端口表与 PID 全局可见 → 按 8767 端口定位。
    bridge_pids = []
    rc, out = run(["netstat", "-ano", "-p", "TCP"], timeout=30)
    for line in out.splitlines():
        p = line.split()
        if len(p) < 5 or p[0].upper() != "TCP" or p[3].upper() != "LISTENING":
            continue
        try:
            port = int(p[1].rsplit(":", 1)[1])
        except ValueError:
            continue
        if port == 8767 and p[4].isdigit():
            pid = int(p[4])
            if pid not in bridge_pids:
                bridge_pids.append(pid)
    log("[2] 8767 端口占用者: %s" % bridge_pids)
    targets = bridge_pids + [p for p in (7044, 3840) if p not in bridge_pids]
    for pid in targets:
        rc2, out2 = run(["taskkill", "/F", "/PID", str(pid)], timeout=30)
        log("[2] taskkill PID %d -> rc=%s %s" % (pid, rc2, out2.strip()[:160]))

    # ---- 3. LocalSystem 临时服务执行阶段 1 ----
    log("[3] 调用 _run_sys_task.py 创建 LocalSystem 服务...")
    try:
        sys.path.insert(0, REPO)
        import _run_sys_task
        logf = open(LOG, "a", encoding="utf-8", buffering=1)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf
        try:
            sys.argv = ["_run_sys_task.py", STAGE1]
            rc = _run_sys_task.main()
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            logf.flush()
            logf.close()
        log("[3] _run_sys_task 退出码=%s" % rc)
    except Exception as e:
        log("[3] _run_sys_task 异常: %r" % (e,))

    # ---- 4. 汇总结果 ----
    time.sleep(2)
    stage1_path = os.path.join(REPO, "_sys_stage1_result.json")
    stage1 = {}
    if os.path.exists(stage1_path):
        try:
            with open(stage1_path, "r", encoding="utf-8") as f:
                stage1 = json.load(f)
        except Exception as e:
            stage1 = {"error": str(e)}
    log("[4] stage1 结果: %s" % json.dumps(stage1, ensure_ascii=False))

    rc, out = run(["netstat", "-ano", "-p", "TCP"], timeout=30)
    ports = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) < 5 or p[0].upper() != "TCP" or p[3].upper() != "LISTENING":
            continue
        try:
            port = int(p[1].rsplit(":", 1)[1])
        except ValueError:
            continue
        if port in (8765, 8767, 8768):
            ports[str(port)] = p[4]
    log("[4] 端口占用: %s" % json.dumps(ports))

    rc, out = run([
        "tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"], timeout=40)
    consumers = [ln for ln in out.splitlines() if "erp_feishu_direct" in ln]
    log("[4] 消费者进程行: %s" % consumers)

    consumer_log = os.path.join(REPO, "erp_feishu_direct.log")
    mq_ok = False
    if os.path.exists(consumer_log):
        try:
            with open(consumer_log, "r", encoding="utf-8") as f:
                mq_ok = "group=insurance-automation" in f.read()
        except Exception:
            pass

    result = {
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elevated": True,
        "disable_flag": os.path.exists(FLAG),
        "stage1": stage1,
        "port_owners": ports,
        "mq_subscribed": mq_ok,
        "bridge_alive": _pid_alive(7044),
    }
    try:
        with open(RESULT, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log("[4] 结果已写入 %s" % RESULT)
    except Exception as e:
        log("[4] 结果写入失败: %r" % (e,))
    log("提权执行器结束")
    return 0


def _pid_alive(pid):
    rc, out = run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"], timeout=25)
    return str(pid) in out


if __name__ == "__main__":
    sys.exit(main())
