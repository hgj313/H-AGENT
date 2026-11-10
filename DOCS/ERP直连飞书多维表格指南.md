# ERP → 飞书多维表格 直连同步

> **不经过保险AI助手服务**。ERP 的 MQ 消息直接写入飞书多维表格。
> 实现目录：`erp_feishu_direct/`
> 分支：`insurance-ai`

---

## 一、与上一版方案的区别

上一版（commit `e11aab4`）是「ERP → 保险AI助手 → 飞书」，数据经由本地 SQLite 与 8765 服务中转。

本版**彻底去掉中间环节**：

| | 上一版 | 本版（直连） |
|---|---|---|
| 数据路径 | ERP → MQ → 8765 → SQLite → 飞书 | ERP → MQ → **直连进程** → 飞书 |
| 依赖 8765 服务 | 是 | **否** |
| 写本地 SQLite | 是（`punch_records`） | **否**（纯内存直传） |
| 实时性 | 秒级（MQ）+ 定时批量 | **秒级（MQ 实时）** |
| 幂等状态 | SQLite 映射表 | 轻量 JSON 文件 |
| 与现有桥接关系 | 共用一条 MQ 链路 | **独立消费组**，各收全量副本 |

> ⚠️ 「独立消费组」是硬性要求。同一个 topic 下，不同消费组各自收到**全量副本**；
> 若用同一个组，两条链路会互相抢消息，导致各收一半。

---

## 二、数据流

```
ERP 打卡
   ↓  MQ: JS_PROD_MQ / tag=CLOCK_RECORD_CREATE
   ↓  消费组: GID_FEISHU_DIRECT_SYNC（独立，不抢桥接的消息）
┌──────────────────────────────────────┐
│ erp_feishu_direct.consumer（独立进程）│
│  ├─ 攒批：3 秒窗口 / 单批 ≤500 条      │
│  ├─ 幂等：日期+身份证号 → record_id   │
│  └─ 写飞书：Bitable 开放 API           │
└──────────────────────────────────────┘
   ↓  POST /bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
   ↓  POST /bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update
飞书多维表格
```

---

## 三、为什么要攒批

ERP 的 MQ 是**逐条**推送打卡的，而飞书 Bitable API 限流 **10 QPS**。
若每条消息调一次接口，几十条打卡就会打满限流。

本进程用一个**滑动窗口**攒批：默认 3 秒内收到的消息合并成一批，
一次性批量写入（单次 ≤500 条）。451 条/天的高峰时段，一批就够。

窗口和批量大小都可在配置里调：

```json
"batch": {
  "window_seconds": 3,      // 攒批等待窗口
  "max_batch_size": 500,    // 单批上限（飞书硬上限 500）
  "consume_batch": 16,      // 单次 MQ 拉取条数
  "wait_seconds": 3         // MQ 长轮询挂起时长
}
```

---

## 四、幂等设计

ERP 的 MQ 消息可能重复投递（网络重试、消费者重启、消息重投）。
若不加控制，同一天同一人的打卡会在飞书表里出现重复行。

**业务主键 = (打卡日期, 身份证号)**，映射关系存在轻量 JSON 文件
`feishu_direct_sync_map.json`：

```json
{
  "2026-11-10": {
    "452428196708182024": "recXXXXXX"
  }
}
```

- 首次收到 → `batch_create`，拿到 `record_id` 存下来
- 再次收到 → `batch_update`，同一行被更新

文件按天分桶，默认保留 7 天自动清理；写盘用「临时文件 + 原子替换」，
进程中断不会留下半截 JSON。

> 同一人**不同日期**仍是两行 —— 打卡表按天记录是正确语义。

---

## 五、接入步骤

### 1. 阿里云 RocketMQ 创建消费组 ⚠️ 必做

**控制台 → 消费者组（Group）→ 新建**，组名填：

```
GID_FEISHU_DIRECT_SYNC
```

不创建会直接报：

```
AccessDenied  MQServerException
"valid resource owner failed. maybe the resource
 MQ_INST_1756405205604856_BX7N4khY%GID_FEISHU_DIRECT_SYNC not created"
```

这一步已实测确认 —— 不预建消费组，MQ 连接直接被拒。

> 已有组 `GID_INSURANCE_AGENT_PROCESS` 是给现有桥接用的，**不要复用**。

### 2. 飞书开放平台建自建应用

开通权限 **`bitable:app`**（查看、评论、编辑和管理多维表格）→ **发布版本**
（自建应用必须发布后才生效）。

从「应用凭证」页拿 `app_id` / `app_secret`。

### 3. 建目标多维表格

**列名**要和默认映射完全一致：

| 飞书列名 | 类型 | 说明 |
|---|---|---|
| 姓名 | 文本 | |
| 身份证号 | 文本 | |
| 项目名称 | 文本 | |
| 班组 | 文本 | |
| 劳务公司 | 文本 | |
| 劳务分类 | 文本 | |
| 审核状态 | 文本 | |
| 电话 | 文本 | |
| 项目经理 | 文本 | |
| 项目经理手机 | 文本 | |
| 项目经理邮箱 | 文本 | |
| 打卡日期 | **日期** | 代码自动转毫秒时间戳并归零到当天零点 |
| 打卡时间 | **日期** | 代码自动转毫秒时间戳 |

从表格 URL 取 `app_token`：`https://xxx.feishu.cn/base/bascnXXXX` → 取 `bascnXXXX`。

### 4. 写配置

```bash
cp erp_feishu_direct_config.json.example erp_feishu_direct_config.json
```

密钥写进 `.env`（**不要**写进 JSON）：

```bash
# .env 追加
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_APP_TOKEN=bascnXXXXXXXXXXXX
```

`ROCKETMQ_ACCESS_KEY` / `ROCKETMQ_SECRET_KEY` 你的 `.env` 里已经有了。

### 5. 启动

```bash
powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键启动直连同步.ps1"
```

启动脚本会检查 venv、配置文件、5 个凭证项，然后后台拉起进程。

**必须用 `H-AGENT\.venv`** —— `mq_http_sdk` 只装在这个 venv 里，
项目根 `.venv` 没有。

### 6. 看日志

```bash
tail -f C:\insurance-automation\erp_feishu_direct.log
```

正常长这样：

```
ERP → 飞书多维表格 直连消费者
  MQ: topic=JS_PROD_MQ tag=CLOCK_RECORD_CREATE group=GID_FEISHU_DIRECT_SYNC
  飞书: app_token=bascnXXX table=tblXXX
  攒批: 窗口 3s / 单批上限 500
收到 MQ 消息 3 条（累计 3）
[写入飞书] 本批 3 条 → 新增 3 / 更新 0 / 跳过 0 / 失败 0（攒批窗口 3.0s）
```

### 7. 停止

```bash
powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键停止直连同步.ps1"
```

---

## 六、文件说明

| 文件 | 职责 |
|---|---|
| `erp_feishu_direct/consumer.py` | 主程序：订阅 MQ → 攒批 → 写飞书 |
| `erp_feishu_direct/config.py` | 配置加载（默认 → JSON → 环境变量） |
| `erp_feishu_direct/mapper.py` | 消息解析 + 字段映射（纯函数） |
| `erp_feishu_direct/store.py` | 幂等映射存储（JSON，原子写） |
| `erp_feishu_direct/writer.py` | 批量写入 + 重试 + DLQ |
| `erp_feishu_direct_config.json.example` | 配置模板 |
| `一键启动直连同步.ps1` / `一键停止直连同步.ps1` | 启停脚本 |

飞书 HTTP 客户端复用 `insurance_agent/infrastructure/feishu_bitable_client.py`
—— 那是纯 HTTP 层，不依赖数据库与业务逻辑，独立进程可直接用。

运行期产物：
- `feishu_direct_sync_map.json` — 幂等映射（自动生成）
- `feishu_direct_dlq.jsonl` — 写入失败的消息（可人工重放）
- `erp_feishu_direct.log` — 运行日志（10MB 轮转，保留 5 份）

---

## 七、常见问题

**Q: `AccessDenied ... not created`**
消费组没在阿里云控制台创建。见步骤 1。

**Q: `FEISHU_APP_ID ... 缺失`**
`.env` 里没配飞书凭证。见步骤 4。

**Q: 飞书报 1254045 FieldNameNotFound**
表里的列名和映射对不上。检查 `mapper.py` 的 `DEFAULT_FIELD_MAPPING`，
或改 `erp_feishu_direct_config.json` 里的 `field_mapping`。

**Q: 飞书报 1254064 DatetimeFieldConvFail**
「打卡日期」「打卡时间」列必须是**日期**类型，不是文本。

**Q: 飞书报 1254062 SingleSelectFieldConvFail**
用了单选列但选项不存在。改成文本类型最省事。

**Q: 飞书里出现重复行**
确认幂等映射文件 `feishu_direct_sync_map.json` 在工作目录且可写。
如果该文件被清空，历史记录会被当成新记录重复新增。

**Q: 没有消息进来**
先确认 ERP 那边打卡是否真的推到了 `JS_PROD_MQ` / `CLOCK_RECORD_CREATE`。
可以临时把配置里的 `tag` 改成空字符串订阅全部 tag 观察。

**Q: 想确认两条链路没互相抢消息**
分别看两个日志的「累计收到」条数 —— 同一段时间内两条链路的条数应该接近，
而不是各占一半。

---

## 八、测试

```bash
.venv/Scripts/python.exe -m pytest tests/test_erp_feishu_direct.py tests/test_erp_feishu_direct_e2e.py -q
```

34 项，覆盖：时间戳转换、消息解析（含双层 JSON、rename）、字段映射、
幂等存储持久化与过期清理，以及用假飞书客户端跑完整闭环
（首次新增 → 重复转更新 → 超 500 条分批）。
