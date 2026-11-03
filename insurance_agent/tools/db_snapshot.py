"""数据库快照工具：SQLite 安全备份 + 定时快照。

背景（2026-11-03 数据清空事故）：
    用户误用「上传 Excel 替换数据」（`/api/personnel/upload-excel` 替换模式），
    该接口先 `clear_insurance_personnel()` 清空全表再写入新数据。
    一次误点 → 3500+ 条保单人员数据全部丢失，只能靠手工备份回滚。

    本模块提供两道防线：
      1. `backup_database()`：任何破坏性操作前先出一份快照（带时间戳）
      2. `run_daily_snapshot()`：定时任务，每日凌晨自动快照 + 保留 N 天

为什么用 SQLite 的 `Connection.backup()` 而不是文件复制：
    - 文件复制在 WAL 模式下可能拿到不完整快照（-wal / -shm 文件未同步）
    - `backup()` 是 SQLite 官方在线备份 API，事务一致，无需停服
"""

import os
import shutil
import sqlite3
from datetime import datetime, timedelta

from insurance_agent.infrastructure import database as db

# 快照存放目录（与 DB 同级，便于统一管理和清理）
SNAPSHOT_DIR = os.path.join(db.DATA_DIR, "snapshots")

# 快照文件名时间戳格式
_TS_FMT = "%Y%m%d_%H%M%S"

# 默认保留天数（保留 30 天）
DEFAULT_KEEP_DAYS = 30


def _ensure_dir() -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    return SNAPSHOT_DIR


def list_snapshots() -> list[dict]:
    """列出已有快照（按时间倒序）。"""
    if not os.path.isdir(SNAPSHOT_DIR):
        return []
    items = []
    for name in os.listdir(SNAPSHOT_DIR):
        if not name.endswith(".db"):
            continue
        path = os.path.join(SNAPSHOT_DIR, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        items.append({
            "name": name,
            "path": path,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    items.sort(key=lambda x: x["name"], reverse=True)
    return items


def backup_database(tag: str = "") -> str:
    """用 SQLite 在线备份 API 生成一份数据库快照，返回快照路径。

    Args:
        tag: 标签（可选），会拼进文件名便于识别，如 "before_replace"

    Returns:
        快照文件的绝对路径
    """
    _ensure_dir()
    stamp = datetime.now().strftime(_TS_FMT)
    suffix = f"_{tag}" if tag else ""
    dest = os.path.join(SNAPSHOT_DIR, f"app{suffix}_{stamp}.db")

    src = db.get_connection()
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return dest


def prune_snapshots(keep_days: int = DEFAULT_KEEP_DAYS) -> int:
    """清理超过保留期的快照，返回删除数量。"""
    if not os.path.isdir(SNAPSHOT_DIR):
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for name in os.listdir(SNAPSHOT_DIR):
        if not name.endswith(".db"):
            continue
        path = os.path.join(SNAPSHOT_DIR, name)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            continue
        if mtime < cutoff:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(os.path.join(db.DATA_DIR, "db_snapshot.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001
        pass
    print(line, end="")


def run_daily_snapshot(keep_days: int = DEFAULT_KEEP_DAYS) -> dict:
    """定时任务：生成每日快照 + 清理过期快照。

    Args:
        keep_days: 快照保留天数（默认 30）

    Returns:
        dict: {success, snapshot_path, size, removed, error}
    """
    result = {"success": False, "snapshot_path": "", "size": 0, "removed": 0, "error": ""}
    try:
        path = backup_database(tag="daily")
        size = os.path.getsize(path)
        removed = prune_snapshots(keep_days=keep_days)
        result.update({
            "success": True,
            "snapshot_path": path,
            "size": size,
            "removed": removed,
        })
        _log(
            f"每日快照完成: {os.path.basename(path)} ({size/1024/1024:.2f} MB), "
            f"清理过期快照 {removed} 个"
        )
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
        _log(f"每日快照失败: {e}")
    return result


def restore_from_snapshot(snapshot_path: str, confirm: bool = False) -> dict:
    """从快照恢复数据库（危险操作，需 confirm=True）。

    恢复前会先把当前库另存一份，避免"用错的快照覆盖掉正确的当前库"。

    Args:
        snapshot_path: 快照文件路径
        confirm: 必须显式传 True 才会执行

    Returns:
        dict: {success, backup_path, restored_from, error}
    """
    result = {"success": False, "backup_path": "", "restored_from": "", "error": ""}
    if not confirm:
        result["error"] = "需要 confirm=True 才会执行恢复"
        return result
    if not os.path.exists(snapshot_path):
        result["error"] = f"快照不存在: {snapshot_path}"
        return result

    try:
        # 恢复前先备份当前库
        cur_backup = backup_database(tag="before_restore")
        result["backup_path"] = cur_backup

        # 用快照覆盖主库文件（先删 -wal/-shm，避免残留旧事务）
        for suffix in ("-wal", "-shm"):
            side = db.DB_PATH + suffix
            if os.path.exists(side):
                try:
                    os.remove(side)
                except OSError:
                    pass
        shutil.copy2(snapshot_path, db.DB_PATH)

        result["success"] = True
        result["restored_from"] = snapshot_path
        _log(
            f"已从快照恢复: {os.path.basename(snapshot_path)} "
            f"→ {db.DB_PATH}（恢复前已备份至 {os.path.basename(cur_backup)}）"
        )
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
        _log(f"快照恢复失败: {e}")
    return result
