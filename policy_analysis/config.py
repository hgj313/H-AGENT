# -*- coding: utf-8 -*-
"""保单分析监听 配置与常量

统一加载两类凭证：
1. 飞书应用凭证（项目根 .env）：FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_APP_TOKEN
   —— 复用 erp_feishu_direct.config.load_config()
2. MiniMax LLM 密钥（H-AGENT/.env）：MINIMAX_API_KEY 等
   —— create_minimax_llm_from_env() 会从环境变量读取
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 目标表 ID（飞书「保险」多维表格 app_token=TMCEbuuera1jU0s0Ibtcvzu3nLe）
INSURANCE_POLICY_TABLE = "tblo8TZFs2eDQtXZ"    # 保险单（保单 PDF 附件 + 保险单号/批单号回写）
WORKER_INSURANCE_TABLE = "tblJssCBnglzleHO"    # 工人保险清单（人员信息回写）

# 「保险单」表字段
ATTACHMENT_FIELD = "保单"        # 附件字段
POLICY_NO_FIELD = "保险单号"      # 回写：保险单号
BATCH_NO_FIELD = "批单号"         # 回写：批单号

# 「工人保险清单」表字段 → 提取结果字段
WORKER_FIELD_MAP = {
    "姓名": "name",
    "证件号码": "id_number",
    "证件类型": "id_type",
    "出生日期": "birth_date",
    "所属公司": "company",
    "起始时间": "start_date",
    "起止时间": "end_date",
    "岗位名称": "job_title",
    "保险公司": "insurance_company",
    "保单类型": "policy_type",
    "保单号": "policy_number",
    "批单号": "batch_policy_number",
}
# 「状态」字段单独映射：由 modification_type 推导（增保→正常，减保→失效）
STATUS_FIELD = "状态"

# 状态文件：记录已处理的 record_id + 附件 file_token 指纹
PROCESSED_STATE_PATH = os.path.join(PROJECT_ROOT, "policy_analysis_processed.json")

# 轮询间隔（秒）
POLL_INTERVAL = 30

# 日志
LOG_PATH = os.path.join(PROJECT_ROOT, "policy_analysis.log")

# H-AGENT/.env（MiniMax key 所在）
HAGENT_ENV_PATH = os.path.join(PROJECT_ROOT, "H-AGENT", ".env")


def _parse_env_file(path: str) -> None:
    """把 .env 文件里尚未存在的键填充进 os.environ（不覆盖已有值）"""
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
    except Exception:
        pass


def load_feishu_config() -> dict:
    """加载飞书凭证配置（复用 erp_feishu_direct 的 load_config）"""
    from erp_feishu_direct.config import load_config
    cfg = load_config()
    return cfg["feishu"]


def load_llm_env() -> None:
    """确保 MiniMax 密钥已注入环境变量（供 create_minimax_llm_from_env 使用）"""
    _parse_env_file(HAGENT_ENV_PATH)


def create_llm_client():
    """创建 MiniMax-M3 LLM 客户端（全量使用 MiniMax，无其他 provider）"""
    load_llm_env()
    from insurance_agent.infrastructure.llm.factory import create_minimax_llm_from_env
    return create_minimax_llm_from_env()
