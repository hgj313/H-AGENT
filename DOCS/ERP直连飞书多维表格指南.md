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
   ↓  消费组: feishu-direct-sync（独立，不抢桥接的消息）
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

> **消费者程序跑在哪里？**
> 飞书开放平台**不提供常驻进程运行环境**，也无法主动订阅外部 MQ —— 它是「被调用方」。
> 所以消费者程序**不在飞书端跑**，仍跑在能同时访问「阿里云 RocketMQ 公网 HTTP 接入点」
> 和「飞书开放平台」的机器上（即你的本机 Windows）。
> 飞书端要做的只是**授权 + 建目的地**（见步骤 2、3）。

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

### 0. 先读这一段：谁跑在哪

| 组件 | 跑在哪 | 说明 |
|---|---|---|
| ERP 打卡推送 | ERP 服务器（现有） | 往 `JS_PROD_MQ` 推 `CLOCK_RECORD_CREATE` |
| **消费者程序** | **你的本机 Windows** | `erp_feishu_direct\consumer.py`，后台常驻 |
| 多维表格 | 飞书云端 | 数据最终落地的地方 |
| 飞书开放平台 | 飞书云端 | **只提供 API，不跑你的程序** |

飞书端**没有**「部署消费者程序」这个动作 —— 飞书开放平台不提供常驻进程环境，
也不能主动去订阅外部 MQ。飞书端要做的是把**目的地**和**授权**准备好。

### 1. 阿里云 RocketMQ 创建消费组 ⚠️ 必做

**控制台 → 消费者组（Group）→ 新建**，组名填：

```
feishu-direct-sync
```

订阅表达式填 `CLOCK_RECORD_CREATE`。

不创建会直接报：

```
AccessDenied  MQServerException
"valid resource owner failed. maybe the resource
 MQ_INST_1756405205604856_BX7N4khY%feishu-direct-sync not created"
```

这一步已实测确认 —— 不预建消费组，MQ 连接直接被拒。

> ⚠️ **现有桥接的组名是 `insurance-automation`（实测有效），绝对不要复用。**
> 同一个消费组内会互相抢消息，两条链路各收一半。
> 自检脚本 `probe.py` 会拦截重名配置。

### 2. 飞书开放平台建自建应用

1. 开发者后台 → 创建企业自建应用
2. **权限管理** → 开通 **`bitable:app`**（查看、评论、编辑和管理多维表格）
3. **版本管理与发布** → 创建版本 → **发布**
   （自建应用不发布，API 调用会直接返回权限错误）
4. 「应用凭证」页拿 `app_id` / `app_secret`

### 3. 建目标多维表格并授权给应用

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

**然后把应用加为这张表的协作者**（这一步最容易漏）：

```
多维表格页面 → 右上角「...」→「...更多」→「添加文档应用」
   → 搜索你的应用 → 权限选「可管理」
```

> 飞书是**双层权限**：应用权限（bitable:app，需管理员审批 + 发布）
> **⊕** 文档权限（必须显式把应用加为这张表的「可管理」协作者）。
> 只开应用权限而不做「添加文档应用」，会出现
> 「查询记录成功但数据为空」或 1254043。
>
> 前提：添加文档应用前，应用至少要开通一个多维表格 API 权限，
> 否则搜索框里根本找不到这个应用。
> 表格若开启了**高级权限**，必须给「可管理」权限，否则同样操作不了。

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

### 5. 自检（强烈建议先跑这步）

```bash
H-AGENT\.venv\Scripts\python.exe -m erp_feishu_direct.probe --write-test
```

这个脚本**不依赖 8765 服务**，会逐项体检：

| 检查项 | 失败含义 |
|---|---|
| 凭证齐备 | `.env` 缺 key |
| 飞书鉴权 | app_id / app_secret 不对 |
| app_token + 数据表列表 | 没做「添加文档应用」，或 app_token 填错 |
| 目标表定位 | table_id / table_name 都没配 |
| 13 列是否齐全 | 缺列 → 写入报 1254045 |
| 日期列类型 | 不是「日期」→ 写入报 1254064 |
| RocketMQ 消费组 | 组没建 → 报 AccessDenied not created |
| 与桥接组重名 | 会互相抢消息，直接拦截 |
| `--write-test` 写→读→删 | 验证写权限，测试记录自动清理 |

全绿再启动消费者，能省掉大量试错。

### 6. 启动

```bash
powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键启动直连同步.ps1"
```

启动脚本会检查 venv、配置文件、5 个凭证项，然后后台拉起进程。

**必须用 `H-AGENT\.venv`** —— `mq_http_sdk` 只装在这个 venv 里，
项目根 `.venv` 没有。

### 7. 看日志

```bash
tail -f C:\insurance-automation\erp_feishu_direct.log
```

正常长这样：

```
ERP → 飞书多维表格 直连消费者
  MQ: topic=JS_PROD_MQ tag=CLOCK_RECORD_CREATE group=feishu-direct-sync
  飞书: app_token=bascnXXX table=tblXXX
  攒批: 窗口 3s / 单批上限 500
收到 MQ 消息 3 条（累计 3）
[写入飞书] 本批 3 条 → 新增 3 / 更新 0 / 跳过 0 / 失败 0（攒批窗口 3.0s）
```

### 8. 停止

```bash
powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键停止直连同步.ps1"
```

---

## 六、文件说明

| 文件 | 职责 |
|---|---|
| `erp_feishu_direct/consumer.py` | 主程序：订阅 MQ → 攒批 → 写飞书 |
| `erp_feishu_direct/probe.py` | **独立自检脚本**（不依赖 8765），启动前体检 |
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
`probe.py` 会直接告诉你组名和该去哪儿建。

**Q: `FEISHU_APP_ID ... 缺失`**
`.env` 里没配飞书凭证。见步骤 4。

**Q: 飞书报 1254045 FieldNameNotFound**
表里的列名和映射对不上。检查 `mapper.py` 的 `DEFAULT_FIELD_MAPPING`，
或改 `erp_feishu_direct_config.json` 里的 `field_mapping`。

**Q: 飞书报 1254064 DatetimeFieldConvFail**
「打卡日期」「打卡时间」列必须是**日期**类型，不是文本。

**Q: 飞书报 1254062 SingleSelectFieldConvFail**
用了单选列但选项不存在。改成文本类型最省事。

**Q: 飞书报 1254043 / 1254002 资源不存在**
多半是**没做「添加文档应用」**。应用权限 ⊕ 文档权限是两层，
只开了 `bitable:app` 但没把应用加为该表的「可管理」协作者，就会这样。

**Q: 飞书里出现重复行**
确认幂等映射文件 `feishu_direct_sync_map.json` 在工作目录且可写。
如果该文件被清空，历史记录会被当成新记录重复新增。

**Q: 没有消息进来**
先确认 ERP 那边打卡是否真的推到了 `JS_PROD_MQ` / `CLOCK_RECORD_CREATE`。
可以临时把配置里的 `tag` 改成空字符串订阅全部 tag 观察。

**Q: 想确认两条链路没互相抢消息**
分别看两个日志的「累计收到」条数 —— 同一段时间内两条链路的条数应该接近，
而不是各占一半。

**Q: 想确认消费组到底存不存在**
用 `probe.py`。注意**不要**用 `/consumer/groupStatus` 接口判断 ——
那是管理级接口，用消息消费的 AK 调用会固定返回 403
`The OwnerId that your Access Key Id associated to is forbidden`，
连已存在的组也查不出来，是个假信号。
`probe.py` 走的是消费端点，靠 `404 MessageNotExist`（组存在）与
`403 AccessDenied ... not created`（组不存在）区分。

---

## 八、测试

```bash
.venv/Scripts/python.exe -m pytest tests/test_erp_feishu_direct.py tests/test_erp_feishu_direct_e2e.py tests/test_erp_feishu_direct_probe.py -q
```

41 项，覆盖：时间戳转换、消息解析（含双层 JSON、rename）、字段映射、
幂等存储持久化与过期清理，以及用假飞书客户端跑完整闭环
（首次新增 → 重复转更新 → 超 500 条分批），
外加自检脚本的各项判定（缺列 / 日期列类型错 / 写测试后清理 / 组名重名拦截）。
