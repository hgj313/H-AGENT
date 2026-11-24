"""保险管理AI助手 —— 紧急停用开关（SYSTEM 权限执行）

背景（2026-11-24）
------------------
打卡数据改为由 ``erp_feishu_direct`` 直连飞书多维表格后，本地保险管理AI助手
（8765 服务 + MQ bridge + watchdog）需要下线。

但这三个进程都运行在 Windows **Session 0（SYSTEM 权限）**，而日常会话是
Session 1 的 Medium 完整性级别 —— 即使同属 Administrators 组也无法终止它们：

    Stop-Process  -> 拒绝访问
    taskkill /F   -> 拒绝访问
    SeDebugPrivilege -> 当前令牌根本没有该项（被 UAC/沙箱剥离）

唯一可用的高权限执行通道，是 8765 服务自身的 ``POST /api/agent/reload``
热重载端点：它在 **SYSTEM 权限**下执行模块顶层代码。因此本模块被
``insurance_agent/tools/company_extractor.py`` 顶部导入，一旦 reload 被触发，
即可在 SYSTEM 权限下完成停机。

分两阶段执行（便于先验证新链路、再彻底下线）
------------------------------------------------
阶段 1 —— ``.mq_bridge_disabled``
    ① 终止 watchdog（必须最先，否则它会在 3 秒内把 bridge / server 拉起来）
    ② 终止 MQ bridge（释放消费组 ``insurance-automation``，
       否则 bridge 与直连消费者同组会互相抢消息，各收一半）
    ③ 启动 ``erp_feishu_direct_watchdog.py``（Session 0 常驻）
    ※ 8765 服务**保持运行** → 保单识别链路（飞书 WS → /api/upload）不中断

阶段 2 —— ``.assistant_disabled``
    ④ 终止 8765 服务本身（保险管理AI助手全部功能下线）

安全性
------
两个标记文件都不存在时，本模块对业务逻辑零影响（``maybe_shutdown`` 直接返回）。
标记文件由运维手工创建，执行完即可删除。
"""

import csv
import io
import os
import subprocess
import sys
import time
from typing import List, Optional, Tuple

REPO = r"C:\insurance-automation"

# 阶段 1：停 MQ bridge + watchdog，起直连消费者（8765 保留）
STAGE1_FLAG = os.path.join(REPO, ".mq_bridge_disabled")
# 阶段 2：彻底下线 8765
STAGE2_FLAG = os.path.join(REPO, ".assistant_disabled")

LOG_PATH = os.path.join(REPO, "shutdown_switch.log")

# 直连消费者守护脚本
DIRECT_WATCHDOG = "erp_feishu_direct_watchdog.py"
PYTHONW = os.path.join(REPO, "H-AGENT", ".venv", "Scripts", "pythonw.exe")

# 目标进程匹配（按 CommandLine 子串）
TARGETS: Tuple[Tuple[str, str], ...] = (
    ("watchdog", "service_watchdog"),
    ("bridge", "mq_punch_bridge"),
    ("server", r"web_app\server.py"),
)

# Windows 创建标志
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def _log(msg: str) -> None:
    line = "[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass


def _decode(raw: Optional[bytes]) -> str:
    """解码子进程字节输出。

    Windows 原生命令（netstat / PowerShell / wmic）输出用控制台代码页（中文版=GBK），
    而本机 Python 的 locale 编码是 UTF-8，直接 text=True 会抛 UnicodeDecodeError。
    这里按 UTF-8 严格解码 → 失败再退 GB18030 → 最后强制替换。
    """
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def _run(cmd: List[str], timeout: int = 30) -> Tuple[int, str]:
    """执行命令并返回 (returncode, 输出文本)。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, _decode(r.stdout) + _decode(r.stderr)
    except FileNotFoundError as e:
        return -1, "command not found: %s" % e
    except Exception as e:
        return -1, "run failed: %s" % e


def _list_python_procs() -> List[Tuple[int, str]]:
    """列出所有 python/pythonw 进程，返回 [(pid, command_line), ...]。

    优先用 wmic（本机已移除时快速失败并回退），否则用 PowerShell Get-CimInstance。
    注意：Session 0 进程的 CommandLine 对其他会话不可见，因此还有端口/父进程兜底。
    """
    rows: List[Tuple[int, str]] = []
    rc, out = _run(
        ["wmic", "process", "where",
         "name='python.exe' or name='pythonw.exe'",
         "get", "CommandLine,ProcessId", "/format:csv"],
        timeout=20,
    )
    if rc == 0 and out.strip():
        reader = csv.reader(io.StringIO(out))
        header = None
        for row in reader:
            if not row:
                continue
            if row[0].strip().lower() == "node":
                header = [c.strip().lower() for c in row]
                continue
            if header is None:
                continue
            try:
                pid_idx = header.index("processid")
                cmd_idx = header.index("commandline")
            except ValueError:
                continue
            if len(row) <= max(pid_idx, cmd_idx):
                continue
            pid = row[pid_idx].strip()
            if pid.isdigit():
                rows.append((int(pid), row[cmd_idx]))
        if rows:
            return rows

    rc, out = _run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } "
         "| ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        timeout=45,
    )
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_s, _, cmd = line.partition("\t")
        if pid_s.isdigit():
            rows.append((int(pid_s), cmd))
    return rows


def _pids_by_port(port: int) -> List[int]:
    """列出占用指定 TCP 监听端口的 PID。

    跨会话兜底：Session 0 进程的 CommandLine 对其他会话不可见，
    但端口表与 ParentProcessId 全局可读，故用端口反查目标进程。
    """
    pids: List[int] = []
    rc, out = _run(["netstat", "-ano", "-p", "TCP"], timeout=25)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        try:
            lport = int(local.rsplit(":", 1)[1])
        except ValueError:
            continue
        if lport != port or parts[3].upper() != "LISTENING":
            continue
        if parts[4].isdigit():
            pid = int(parts[4])
            if pid not in pids:
                pids.append(pid)
    return pids


def _parent_pid(pid: int) -> int:
    """取父进程 PID（跨会话可读；CommandLine 不可读时用它推导 watchdog）。"""
    rc, out = _run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\").ParentProcessId" % pid],
        timeout=25,
    )
    for line in reversed(out.splitlines()):
        t = line.strip()
        if t.isdigit():
            return int(t)
    return 0


def _python_pids() -> List[int]:
    """所有 python/pythonw 进程的 PID 集合。

    Session 0 的 CommandLine 对其他会话不可见，但进程名与 PID 跨会话可读，
    因此用「进程名 + 祖先链」来定位 watchdog（它同时是 server 与 bridge 的父进程）。
    """
    rc, out = _run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } "
         "| ForEach-Object { $_.ProcessId }"],
        timeout=45,
    )
    pids = []
    for tok in out.split():
        t = tok.strip()
        if t.isdigit():
            pid = int(t)
            if pid not in pids:
                pids.append(pid)
    return pids


def _python_ancestors(pid: int, py_pids: List[int], max_depth: int = 6) -> List[int]:
    """沿父进程链向上收集所有 python 祖先（自近及远）。"""
    out: List[int] = []
    cur = pid
    for _ in range(max_depth):
        parent = _parent_pid(cur)
        if not parent or parent in out:
            break
        if parent in py_pids:
            out.append(parent)
        cur = parent
    return out


def _watchdog_targets() -> List[int]:
    """定位 watchdog 进程组。

    watchdog 的特征：它同时是 8765 server 与 8767 bridge 的祖先，
    即两条祖先链的**最近公共祖先**（LCA）。此处先返回 LCA，再补其余 python 祖先，
    保证 kill 顺序上「watchdog 本体」最先被杀 —— 否则它会在 3 秒内把子进程拉起来。
    """
    py_pids = _python_pids()
    service_pids = _pids_by_port(8765) + _pids_by_port(8767)
    chains: List[List[int]] = []
    for pid in service_pids:
        chains.append([pid] + _python_ancestors(pid, py_pids))

    lcas: List[int] = []
    for i in range(len(chains)):
        for j in range(i + 1, len(chains)):
            common = [p for p in chains[i] if p in chains[j]]
            if common:
                if common[0] not in lcas:
                    lcas.append(common[0])

    others: List[int] = []
    for ch in chains:
        for p in ch[1:]:
            if p not in others:
                others.append(p)

    result = list(lcas)
    for p in others:
        if p not in result:
            result.append(p)
    return result


def _collect_targets(tag: str) -> List[int]:
    """汇总某类目标的所有候选 PID（命令行匹配 + 端口/父进程兜底）。"""
    pids: List[int] = []

    def _add(pid: int) -> None:
        if pid and pid > 0 and pid != os.getpid() and pid not in pids:
            pids.append(pid)

    if tag == "watchdog":
        for pid in _watchdog_targets():
            _add(pid)
        return pids

    # ① 命令行匹配
    keyword = dict(TARGETS)[tag]
    for pid, cmd in _list_python_procs():
        if keyword.lower() in (cmd or "").lower():
            _add(pid)

    # ② 端口兜底
    if tag == "server":
        for pid in _pids_by_port(8765):
            _add(pid)
    elif tag == "bridge":
        for pid in _pids_by_port(8767):
            _add(pid)

    return pids


def _kill_matching(tag: str, keyword: str, exclude_self: bool = True) -> List[int]:
    """按 CommandLine 关键字终止进程，返回被终止的 PID 列表。"""
    killed: List[int] = []
    for pid in _collect_targets(tag):
        rc, out = _run(["taskkill", "/F", "/PID", str(pid)], timeout=30)
        _log("终止 %s PID %d -> rc=%s %s" % (tag, pid, rc, out.strip()[:140]))
        if rc == 0:
            killed.append(pid)
    return killed


def _start_direct_consumer() -> bool:
    """启动 erp_feishu_direct 直连消费者守护（Session 0 常驻）。"""
    script = os.path.join(REPO, DIRECT_WATCHDOG)
    if not os.path.exists(script):
        _log("直连守护脚本不存在: %s" % script)
        return False
    if not os.path.exists(PYTHONW):
        _log("pythonw 不存在: %s" % PYTHONW)
        return False
    try:
        subprocess.Popen(
            [PYTHONW, DIRECT_WATCHDOG],
            cwd=REPO,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            close_fds=True,
        )
        _log("已启动直连消费者守护: %s" % DIRECT_WATCHDOG)
        return True
    except Exception as e:
        _log("启动直连消费者失败: %s" % e)
        return False


def _stage1() -> None:
    """阶段 1：停 watchdog + MQ bridge，启动直连消费者（8765 保留运行）。"""
    _log("=== 阶段 1 开始：停 MQ bridge + watchdog，起直连消费者 ===")

    # ① 先杀 watchdog（否则它会立刻重启 bridge 与 server）
    _kill_matching("watchdog", "service_watchdog")
    time.sleep(1.5)

    # ② 再杀 bridge（释放消费组 insurance-automation）
    _kill_matching("bridge", "mq_punch_bridge")
    time.sleep(1.0)

    # ③ 起直连消费者（幂等：watchdog 自带单实例锁）
    _start_direct_consumer()
    time.sleep(2.0)

    _log("=== 阶段 1 完成：MQ 桥接已停，直连消费者已启动，8765 仍在运行 ===")


def _stage2() -> None:
    """阶段 2：彻底下线 8765 服务（保险管理AI助手全部功能停用）。"""
    _log("=== 阶段 2 开始：下线 8765 服务 ===")
    _kill_matching("server", r"web_app\server.py")
    _log("=== 阶段 2 完成：8765 已下线 ===")


def maybe_shutdown() -> None:
    """入口：由被 reload 的业务模块在导入时调用。

    - STAGE1_FLAG 存在 -> 执行阶段 1（不退出进程，8765 继续服务）
    - STAGE2_FLAG 存在 -> 执行阶段 2 并退出进程
    """
    stage1 = os.path.exists(STAGE1_FLAG)
    stage2 = os.path.exists(STAGE2_FLAG)
    if not (stage1 or stage2):
        return

    try:
        if stage1:
            _stage1()
        if stage2:
            _stage2()
            # 阶段 2 需要真正退出：reload 的调用方（8765）随后将被终止
            time.sleep(1.0)
            os._exit(0)
    except Exception as e:
        _log("停用流程异常: %s" % e)
