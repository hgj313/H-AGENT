"""直连同步的配置加载

配置来源优先级（后者覆盖前者）：
1. 代码内置默认值
2. `erp_feishu_direct_config.json`（非敏感项：topic/group/映射表等）
3. 环境变量 / `.env`（敏感项：AK/SK、飞书 app_secret 等）

安全约定
--------
- **密钥不写进 JSON**，一律走环境变量（ROCKETMQ_ACCESS_KEY / ROCKETMQ_SECRET_KEY /
  FEISHU_APP_ID / FEISHU_APP_SECRET），与项目既有约定一致。
- 飞书 app_secret 若确实要落配置，也会被日志脱敏。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 包目录：<项目根>/erp_feishu_direct
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "erp_feishu_direct_config.json")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# 幂等映射文件（记录 打卡日期+身份证号 → 飞书 record_id）
SYNC_MAP_PATH = os.path.join(PROJECT_ROOT, "feishu_direct_sync_map.json")

# DLQ（飞书写入失败的消息）
DLQ_PATH = os.path.join(PROJECT_ROOT, "feishu_direct_dlq.jsonl")

# 单实例锁端口（独立于 8765 业务端口与 8767 MQ 桥接锁）
LOCK_PORT = 8768


def default_config() -> Dict[str, Any]:
    """内置默认配置"""
    return {
        "mq": {
            "backend": "rocketmq",
            "protocol": "http",
            "host": "http://1756405205604856.mqrest.cn-qingdao-public.aliyuncs.com",
            "port": 80,
            "instance_id": "MQ_INST_1756405205604856_BX7N4khY",
            "access_key": "",
            "secret_key": "",
            "topic": "JS_PROD_MQ",
            "tag": "CLOCK_RECORD_CREATE",
            # ⚠️ 必须与现有 MQ 桥接（GID_INSURANCE_AGENT_PROCESS）使用**不同的消费组**，
            #    否则两条链路会互相抢消息，导致各自只收到一半。
            # ⚠️ 阿里云 RocketMQ 的消费组必须**先在控制台创建**，否则连接报
            #    AccessDenied: resource MQ_INST_xxx%<group> not created。
            "group": "GID_FEISHU_DIRECT_SYNC",
            "use_tls": False,
            "max_consecutive_errors": 5,
        },
        "feishu": {
            "app_id": "",
            "app_secret": "",
            "app_token": "",
            "table_id": "",
            "table_name": "",
            "timeout": 15,
        },
        # 攒批参数：MQ 逐条推送，飞书批量写入，用滑动窗口合并
        "batch": {
            "window_seconds": 3,     # 攒批等待窗口
            "max_batch_size": 500,   # 单批最大条数（飞书上限 500）
            "consume_batch": 16,     # 单次 MQ 拉取条数（上限 16）
            "wait_seconds": 3,       # MQ 长轮询挂起时长
        },
        "sync": {
            "enabled": True,
            # 幂等映射文件保留天数（过期后清理，防止无限增长）
            "map_keep_days": 7,
            "retry": 3,
            "retry_backoff": 2.0,
        },
        # ERP 字段名 → 本地标准字段名（沿用桥接程序的 rename 思路）
        "rename": {
            "employeeName": "memberName",
            "idCard": "identificationNumber",
            "employeeId": "memberId",
            "project": "projectName",
            "team": "teamName",
            "supplier": "supplierName",
            "category": "categoryName",
            "phone": "telephone",
            "clockTime": "punchTime",
            "signTime": "punchTime",
            "signInTime": "punchTime",
            "attendTime": "punchTime",
            "checkinTime": "punchTime",
            "punchDateTime": "punchTime",
            "firstPunchTime": "punchTime",
            "lastPunchTime": "punchTime",
            "打卡时间": "punchTime",
            "打卡日期": "punchTime",
        },
    }


def _deep_update(base: dict, over: dict) -> None:
    """递归合并配置（over 覆盖 base）"""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def load_dotenv(path: str = ENV_PATH) -> None:
    """极简 .env 解析：只填充尚未存在的环境变量，不覆盖已有值"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        logger.debug("已加载 .env: %s", path)
    except Exception as e:  # noqa: BLE001
        logger.warning(".env 加载失败: %s", e)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """加载完整配置：默认值 → JSON 文件 → 环境变量"""
    cfg = default_config()

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                _deep_update(cfg, user)
                logger.info("已加载配置: %s", path)
        except Exception as e:  # noqa: BLE001
            logger.warning("配置加载失败，使用默认值: %s", e)

    load_dotenv()

    mq = cfg["mq"]
    fs = cfg["feishu"]

    # 环境变量覆盖（敏感项）
    mq["access_key"] = os.environ.get("ROCKETMQ_ACCESS_KEY") or os.environ.get("MQ_ACCESS_KEY") or mq.get("access_key", "")
    mq["secret_key"] = os.environ.get("ROCKETMQ_SECRET_KEY") or os.environ.get("MQ_SECRET_KEY") or mq.get("secret_key", "")
    fs["app_id"] = os.environ.get("FEISHU_APP_ID") or fs.get("app_id", "")
    fs["app_secret"] = os.environ.get("FEISHU_APP_SECRET") or fs.get("app_secret", "")
    fs["app_token"] = os.environ.get("FEISHU_APP_TOKEN") or fs.get("app_token", "")

    # 非敏感项也允许环境变量覆盖
    for env_key, cfg_path in (
        ("MQ_HOST", ("mq", "host")),
        ("MQ_PORT", ("mq", "port")),
        ("MQ_INSTANCE_ID", ("mq", "instance_id")),
        ("MQ_TOPIC", ("mq", "topic")),
        ("MQ_TAG", ("mq", "tag")),
        ("MQ_GROUP", ("mq", "group")),
    ):
        val = os.environ.get(env_key)
        if val:
            section, key = cfg_path
            cfg[section][key] = int(val) if key == "port" else val

    return cfg


def is_configured(cfg: Dict[str, Any]) -> bool:
    """检查必要凭证是否齐备"""
    mq, fs = cfg["mq"], cfg["feishu"]
    missing = []
    if not mq.get("access_key"):
        missing.append("ROCKETMQ_ACCESS_KEY")
    if not mq.get("secret_key"):
        missing.append("ROCKETMQ_SECRET_KEY")
    if not fs.get("app_id"):
        missing.append("FEISHU_APP_ID")
    if not fs.get("app_secret"):
        missing.append("FEISHU_APP_SECRET")
    if not fs.get("app_token"):
        missing.append("FEISHU_APP_TOKEN")
    return missing


def missing_keys(cfg: Dict[str, Any]) -> list:
    """返回缺失的凭证名列表"""
    mq, fs = cfg["mq"], cfg["feishu"]
    missing = []
    if not mq.get("access_key"):
        missing.append("ROCKETMQ_ACCESS_KEY")
    if not mq.get("secret_key"):
        missing.append("ROCKETMQ_SECRET_KEY")
    if not fs.get("app_id"):
        missing.append("FEISHU_APP_ID")
    if not fs.get("app_secret"):
        missing.append("FEISHU_APP_SECRET")
    if not fs.get("app_token"):
        missing.append("FEISHU_APP_TOKEN")
    return missing
