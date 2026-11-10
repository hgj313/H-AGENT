"""ERP → 飞书多维表格 直连同步包

独立于保险AI助手服务运行：
- 不经过 web_app/server.py（8765 端口）
- 不写本地 SQLite（纯内存直传）
- 只依赖 requests + mq_http_sdk

数据流::

    ERP 打卡 → RocketMQ(JS_PROD_MQ / CLOCK_RECORD_CREATE)
                    ↓ 独立消费组 feishu-direct-sync
              erp_feishu_direct.consumer
                    ↓ 攒批（滑动窗口）
              erp_feishu_direct.mapper   ← 字段映射（纯函数）
                    ↓
              erp_feishu_direct.writer   ← 批量写飞书
                    ↓
              飞书多维表格（Bitable 开放 API）

幂等状态：轻量 JSON 文件（feishu_direct_sync_map.json），只存
「打卡日期+身份证号 → 飞书 record_id」的对应关系，用于重复消息时改为更新而非新增。
"""

__version__ = "1.0.0"
