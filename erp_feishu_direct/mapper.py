"""MQ 打卡事件 → 飞书多维表格字段映射

纯函数模块，不依赖网络与数据库，便于单独测试。

关键点
------
1. **日期列必须传毫秒时间戳**：飞书日期字段只接受 13 位毫秒时间戳（int），
   传字符串会报 1254064。
2. **数字列必须传数字**：飞书数字字段不接受字符串与布尔值。
3. **空值不写入**：字段缺失时直接跳过该列，避免用空串污染飞书表格。
4. **打卡日期兜底**：ERP 消息常只带 `punchTime`（时间戳），没有独立的日期字段，
   此时从打卡时间中提取日期部分。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 飞书列名 → ERP 标准字段名（与主项目 punch_records 的字段语义保持一致）
DEFAULT_FIELD_MAPPING = {
    "姓名": "memberName",
    "身份证号": "identificationNumber",
    "项目名称": "projectName",
    "班组": "teamName",
    "劳务公司": "supplierName",
    "劳务分类": "categoryName",
    "审核状态": "examinationStatusName",
    "电话": "telephone",
    "项目经理": "projectManager",
    "项目经理手机": "managerPhone",
    "项目经理邮箱": "managerEmail",
    "打卡日期": "punchDate",
    "打卡时间": "punchTime",
}

# 兜底字段链：ERP 的 MQ 消息通常只带 punchTime，不带独立的 punchDate，
# 所以「打卡日期」列需要从多个候选字段里依次取，取到第一个非空值即止。
_FALLBACK_FIELDS = {
    "打卡日期": ("punchDate", "punchTime", "clockTime", "signTime", "attendTime"),
    "打卡时间": ("punchTime", "clockTime", "signTime", "attendTime", "punchDate"),
}

# 需要转毫秒时间戳的列
DATE_FIELDS = {"打卡日期", "打卡时间"}

# 需要转数字的列
NUMBER_FIELDS = {"年龄"}

# 时间字符串 → 毫秒时间戳 支持的格式
_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    "%Y/%m/%d",
]


def to_millis(raw: Any) -> Optional[int]:
    """把时间值转成 13 位毫秒时间戳；无法解析返回 None"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        val = int(raw)
        # 10 位秒 → 13 位毫秒
        return val * 1000 if val < 10_000_000_000 else val

    s = str(raw).strip()
    if not s:
        return None

    if s.isdigit() and len(s) in (10, 13):
        val = int(s)
        return val * 1000 if len(s) == 10 else val

    for fmt in _TIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue

    try:
        iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        logger.debug("无法解析时间: %r", raw)
        return None


def to_number(raw: Any) -> Optional[float]:
    """把值转成数字；空值/非法值/布尔返回 None"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return raw
    try:
        val = float(str(raw).strip())
        return int(val) if val.is_integer() else val
    except (ValueError, TypeError):
        return None


def to_date_millis(raw: Any) -> Optional[int]:
    """把时间值转成「当天零点」的毫秒时间戳

    「打卡日期」列只关心日期部分：即使原始值是 "2026-11-10 08:32:00"，
    也应落到当天 00:00:00，避免日期列里带出时分秒。
    """
    ms = to_millis(raw)
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000)
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError, OverflowError):
        return ms


def extract_punch_date(event: Dict[str, Any]) -> str:
    """提取打卡日期 YYYY-MM-DD

    优先用事件自带的 punchDate；没有则从 punchTime 里取日期部分；
    都没有则用当前日期（ERP 消息一般总会带其中之一）。
    """
    raw = event.get("punchDate")
    if raw:
        s = str(raw).strip()
        if len(s) >= 10 and s[4] in "-/" and s[7] in "-/":
            return s[:10].replace("/", "-")

    punch_time = event.get("punchTime")
    if punch_time:
        s = str(punch_time).strip()
        if len(s) >= 10 and s[4] in "-/" and s[7] in "-/":
            return s[:10].replace("/", "-")

    return datetime.now().strftime("%Y-%m-%d")


def build_fields(
    event: Dict[str, Any],
    mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """把一条 MQ 打卡事件转成飞书 fields 字典

    Args:
        event: ERP 打卡事件（已按 rename 归一化字段名）
        mapping: 飞书列名 → ERP 字段名；默认用 DEFAULT_FIELD_MAPPING

    Returns:
        可直接写入飞书的 fields 字典
    """
    mapping = mapping or DEFAULT_FIELD_MAPPING
    fields: Dict[str, Any] = {}

    for feishu_col, erp_key in mapping.items():
        raw = event.get(erp_key)
        if raw is None or raw == "":
            # 主字段缺失 → 按兜底链依次尝试（ERP 消息常只带 punchTime）
            for alt_key in _FALLBACK_FIELDS.get(feishu_col, ()):
                if alt_key == erp_key:
                    continue
                alt = event.get(alt_key)
                if alt is not None and alt != "":
                    raw = alt
                    break

        if raw is None or raw == "":
            continue

        if feishu_col in DATE_FIELDS:
            # 「打卡日期」只取日期部分（当天零点），「打卡时间」保留完整时分秒
            ms = to_date_millis(raw) if feishu_col == "打卡日期" else to_millis(raw)
            if ms is not None:
                fields[feishu_col] = ms
        elif feishu_col in NUMBER_FIELDS:
            num = to_number(raw)
            if num is not None:
                fields[feishu_col] = num
        else:
            fields[feishu_col] = str(raw)

    return fields


def normalize_events(raw: Any, rename: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """从 MQ 原始消息体解析出事件列表（沿用桥接程序的兼容策略）

    ERP 可能发送：JSON 数组 / {"events":[...]} / {"data":[...]} / 单条对象，
    也可能把整个 JSON 再用引号包一层（Java/Kotlin 序列化常见）。
    """
    import json

    rename = rename or {}

    if raw is None:
        return []
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # 最多剥 3 层 JSON 字符串
        for _ in range(3):
            try:
                raw = json.loads(s)
            except Exception:
                logger.warning("MQ 消息非 JSON，已忽略: %s", s[:120])
                return []
            if not isinstance(raw, str):
                break
            s = raw.strip()
            if not s:
                return []

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = None
        for key in ("events", "data", "records", "items", "list"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
        if items is None:
            items = [raw]
    else:
        return []

    events = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ev = {}
        for k, v in it.items():
            ev[rename.get(k, k)] = v
        events.append(ev)
    return events
