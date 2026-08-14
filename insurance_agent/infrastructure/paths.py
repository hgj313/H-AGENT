"""统一路径配置

集中管理项目根目录和数据目录，支持通过环境变量覆盖（用于 Docker 部署）。

环境变量：
- APP_HOME: 项目根目录（默认根据本文件位置推断）
- DATA_DIR: 数据目录（默认 <APP_HOME>/data）

本地开发（Windows）无需设置任何环境变量，自动推断为项目根目录。
Docker 部署时通过 ENV 设置 APP_HOME=/app、DATA_DIR=/app/data 即可。
"""

import os

# 项目根目录：本文件位于 <项目根>/insurance_agent/infrastructure/paths.py
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.environ.get("APP_HOME", _PROJECT_ROOT)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))

# 常用子目录
POLICY_LIBRARY_DIR = os.path.join(PROJECT_ROOT, "policy_library")
PDF_STORAGE_DIR = os.path.join(DATA_DIR, "policy_pdfs")

# 提醒配置文件
REMINDER_CONFIG_PATH = os.path.join(PROJECT_ROOT, ".reminder_config.json")

# 调度器配置
SCHEDULER_CONFIG_PATH = os.path.join(DATA_DIR, "scheduler_config.json")
