# 保险单识别项目核心记忆

## 项目目标
从保险单 PDF 提取被保人员清单（姓名/证件号/所属公司/起止时间/保险公司/批改类型）。批单→主保单自动关联补全日期。

## 保险单格式速查（保险公司 → 清单格式 / 逐人日期 / 用工单位 / 增减保）
- **利宝**（保单/短期/批单/BD）：table+inline，整体日期，用工单位✅，纯增。BD 文件名 `公司名_保单号_BD.pdf`
- **太保**（ASHH主/BSHH批）：table，明细有日期/清单无，✅，纯增。安诚已归太保
- **华农**（保单/批单）：table/inline，整体/批改日，✅，增删
- **中国人寿-在保名单**：**block_kv**，逐人日期，✅「投保人」，增/减替
- **中国人寿-变动清单**：table 双栏，减栏无 ID→无法去失效
- **中国人寿财险**：table，整体，无用工单位，纯增
- **黄河**（批单）：table 变动清单，增/删 ｜ **黄河扫描件**：OCR table，"共同被保险人"，"工种类"易误填 company
- **华安**（批单）：table，增/删，续保批改，用工单位跨行
- **众安在线**（非灵工）：table，纯增，"人员名单"头词 ｜ **众安灵工版**：no_list(不记名)
- **北部湾/平安产险/平安养老/大地PZFZ/申能**：table，整体，投保人=被保险人。平安养老起止两条独立字段；大地9页；平安产险20位保单号
- **阳光HGC**：table+inline，`End.NO.<batch>`/`PolicyNO.<main>` ｜ **阳光变更**：inline，`姓名由X变更为Y`
- **平安-投保单**：no_list（仅条款）

## 关键识别规则
- 文件名含"投保单"≠投保申请书：仅当同时无保单号且无清单页才判 `no_list`
- 中介黑名单：`保险经纪`/`代理公司`/`保险公估` → 跳 `parse_policy_filename`
- 清单页定位：`_LIST_MARKERS` → `_is_real_list_page`(表头词+6位数字) → 排除 `_is_clause_page`；续页 `_is_list_continuation_page`(≥3 身份证，含脱敏)
- `_is_real_list_page` header 主判据"姓名/雇员姓名"；无姓名但含"证件号"且不含"统一社会信用代码"才兜底
- table_extractor post_region 双重截断：① 截到下个身份证号前 ② 截到 `\n\n` 前（PDF 页边界，防跨页抓页脚）
- table_extractor 工种 post 优先 + "建筑工"排除；⚠️ 不能改 pre 优先
- PyMuPDF 身份证跨行拆分 → `re.sub` 跨行拼接（众安/大地/申能）
- 保单号标签 `保险单号码?` 兼容多"码"字
- 日期空格：`2026 年 10 月 01 日` → 年/月/日两侧加 `\s*`
- 工种双字段：`_OCCUPATION_CLASS_PATTERN`→occupation_class；`_JOB_PATTERN`→job_title；job_title 空则退化
- 跨行工种合并：`X类职业\n工种` → 合并前"职业"后插 `\ue000`，合并后还原（⚠️ 不能用 `\x00`）
- 利宝批单生效日重复 → `_strip_zero_count_remove_markers` + `_is_repeated_effective_date`（起止同天且重复→清空交 validator 回填）

## date_parser 整体期间矩阵
- 「自X起至Y止」：日期间允许任意中文+数字+时间词
- 「自北京时间X起至Y止」：⚠️ "自"与年份间可插时区口径词 → `_TIMEZONE_PREFIX` 可选前缀
- 「保险起期/止期（北京时间）」：两条独立字段（平安养老）
- block_kv 双字段顺序不固定 → 取 min/max

## 身份证脱敏四种格式
完整 18 位 / `412702********2432`(6+8+4) / `51102519741110****`(14+4) / 通用正则 `(?:\d{6}\*{6,10}\d{0,4}[\dXx]?|\d{14}\*{4})`
- 保留 * 号入库不反推（用户指令）；校验只查地区码前缀
- ⚠️ 扩展正则必须写回归测试覆盖旧+新+混合（教训：inline_extractor `_ID_REGEX`、date_parser `_OVERALL_PATTERNS`）
- ⚠️ 脱敏 ID → "打卡无正常保单"误报（10-28）：用户定**不改代码，走人工补全**（`data/待人工补全身份证号清单.csv` + `tools/fill_masked_id_numbers.py --apply`）。同类问题先问

## 技术方案
PDF：PyMuPDF 文字层 + 扫描件 MiniMax-M3 视觉 OCR。LangGraph：policy_parser → metadata_extractor → personnel_extractor → validator → output。Extractors：table/inline/individual/block_kv/ocr。LLM：MiniMax-M3（Anthropic 协议，H-AGENT/.env）。服务：FastAPI（web_app/server.py :8765）+ service_watchdog.py。

## 关键设计
- 批单→主保单关联（L1 validator `_link_to_main_policy` / L2 policy_library 兜底 / L3 缺失报错）；`_policy_numbers_compatible` 前缀兼容（利宝批单71XX vs 主81XX）
- 保单库双表：`policy_library.register()` 分流 `index_main.json`/`index_batch.json`
- 公司识别 3 层：L1 `_COMPANY_PATTERNS` 长词优先 → L2 命中加权 → L3 `detect_insurance_company_by_policy_number` 号段兜底（最强）。已注册：613010104=华安 / 81160=利宝 / 61160=安诚 / ASHH,BSHH,X44,SHBX=太保 / 804147=北部湾 / PEAC=平安养老 / PZFZ=大地 / 6513=申能

## 数据库与去重
- 表 `insurance_personnel`；判重键 `(name, id_number)`；partial UNIQUE INDEX `idx_person_name_id_uniq ... WHERE id_number != ''`（11-05 重建）
- **11-05 规则变更**：「同一姓名同一身份证号只保留一条」（原"同人跨保单多条=续保轨迹"已推翻）——这是「本地11人 vs 飞书22人」统计失真的根因
- 写侧去重：`upsert_insurance_personnel_detailed()` → `{written,added,updated,collapsed,skipped,details}`；`_decide_replace()` 新数据排序键更大才替换；**例外**：旧记录止期未知且新数据仍在有效期→替换；完全等价→仅当能补齐空字段才替换
- 排序键 `_personnel_rank()` = `(end_date, start_date, status有效, policy_number非空, id)`，空日期=`9999-12-31`。⚠️ 比较新旧只取前 4 项（不含 id）
- end 优先于 start（218 组实测 0 分歧）；新数据日期为空时保留原日期（防在保被误降失效）
- 收敛历史重复：替换前吸收其余行非空字段再删 → 一人一行
- 旧 `ON CONFLICT(name,id,policy)` 已废除（保单号不同会 INSERT → 重复再生源）
- `db.normalize_person_status()` 白名单；`deactivate_insurance()` 加参数必须 grep 全部调用点
- 跑 web_app.server 必须用 **`H-AGENT/.venv/Scripts/python.exe`**；pytest 用项目根 `.venv`
- 去重工具 `tools/dedupe_insurance_personnel.py`：dry-run 默认，`--apply` 执行。⚠️ 字段合并绝不能含 start_date/end_date；⚠️ 先 DELETE 再 UPDATE（UNIQUE 冲突）

## 数据安全
- 快照 `insurance_agent/tools/db_snapshot.py` → `data/snapshots/`，用 `Connection.backup()`（不能直接拷文件，WAL 未同步）。定时 03:00，保留 30 天
- `/api/personnel/upload-excel` = **替换**（先清空全表）三道防线：① `?confirm=true` ② 清空前自动快照 ③ Excel 条数 < 库中 30% 拒绝。`upload-excel-add` = 追加（安全）
- 快照 API：`GET /api/db/snapshots` / `POST /api/db/snapshot` / `POST /api/db/restore?name=&confirm=true`
- ⚠️ FastAPI 路由 `request: Request` 必须放在无默认值参数之前

## ERP / MQ / 短信
- page_size：fetch_all_punch_data=500、fetch_project_orders=500、fetch_user_list=1000
- 打卡链路：ERP `findCompleteLaborCalculation/page`（HMAC-SHA256 签名，X-Timestamp/X-Nonce/X-Sign）→ `coverage_check.sync_punch_data()` 三接口并发 → `db.upsert_punch_records()` → 表 `punch_records` UNIQUE(punch_date, identification_number)
- MQ：topic=`JS_PROD_MQ`、tag=`CLOCK_RECORD_CREATE`、**group=`insurance-automation`**、endpoint 带 `-public`
- ⚠️ **消费组真实名是 `insurance-automation`**（桥接日志实测）；历史文档里的 `GID_INSURANCE_AGENT_PROCESS` 是「语义命名」，实际**不存在**（实测 403 not created）。记「意图」不记「字符串」
- ⚠️ **消费组必须在阿里云控制台预建**，否则消费报 `AccessDenied ... MQ_INST_xxx%<group> not created`
- ⚠️ **`/consumer/groupStatus` 不能用来判消费组是否存在** —— 管理级接口，用消费 AK 调用固定 403 `OwnerId ... forbidden`，连已存在的组也查不出（假信号）。改用消费端点探活：`404 MessageNotExist`=组存在、`403 not created`=组不存在
- ⚠️ 消费请求的 **tag 也参与资源键校验**：拿不存在的 tag 去消费，即使组存在也报 not created
- 双 dedup：`last_daily_check.punch_date`（force 可绕）+ `daily_sms_sent_today.phones`（force 不可绕）
- ⚠️ **通知安全规则**：`/api/summary/trigger?force=true`、`/api/reminder/check-expiry`、`/api/daily-check?force=true`、改 `notification_test_mode` 前**必须问用户**；例外=scheduler 定时任务
- 双开关勿混：A=`punch_table_for_sms`（数据源），B=`notification_test_mode`（通知路由）

## 飞书链路（现有）
- `insurance_agent/tools/feishu_webhook_pusher.py`：**自动化 webhook**（`.feishu_webhook.json`），推「未参保人员」到多维表格，异步队列+单 worker、Bearer Token、Client-Token 幂等(3h)、本地 `feishu_push_dedup.json` 跨链路去重、失败落 `feishu_webhook_dlq.jsonl`
- 时间列格式 `YYYY/MM/DD HH:MM`（`_format_punch_time_for_feishu`）
- 局限：一次一条、只能新增、限 10 QPS → **不适合全量打卡同步**（449 条/天）
- `feishu-uploader-plugin/` 是飞书多维表格**自动化插件**（附件 PDF → 本地 /api/upload），方向相反
- ⚠️ 待建：全量打卡同步应走 **Bitable 开放 API**（tenant_access_token + app_token + table_id + batch_create/batch_update，单次 500 条）

## 飞书直连链路（ERP MQ → 飞书，独立进程）
- 目录 `erp_feishu_direct/`：**不经过 8765、不写 SQLite**，纯内存直传 + JSON 幂等映射
- `consumer.py`（主程序）/ `probe.py`（**独立自检，不依赖 8765**）/ `config.py` / `mapper.py` / `store.py` / `writer.py`
- 消费组 `feishu-direct-sync`（≠ 桥接的 `insurance-automation`）；攒批 3s 窗口 / 单批 ≤500；单实例锁端口 8768
- 幂等：业务主键 `(打卡日期,身份证号)` → 飞书 `record_id`，存 `feishu_direct_sync_map.json`（原子写，按天分桶留 7 天）
- ⚠️ 飞书**双层权限**：应用权限 `bitable:app`（+发布版本）**⊕** 文档权限（多维表格「...」→「...更多」→「添加文档应用」加为**可管理**）。只做前者会 1254043/数据为空
- ⚠️ 日期列必须传 **13 位毫秒 int**（字符串报 1254064）；「打卡日期」归零到当天零点、「打卡时间」保留时分秒
- ⚠️ **消费者程序不在飞书端跑** —— 飞书开放平台不提供常驻进程、不能主动订阅外部 MQ，它是「被调用方」
- 必用 `H-AGENT\.venv`（`mq_http_sdk` 只装在这）；`mq_http_sdk` 需 Python 3.12+ 兼容补丁（去 `HTTPSConnection` 的 `strict` 参数）

## 服务稳定性
- 8765 **仅 127.0.0.1 监听**。常驻：计划任务 `InsuranceAgentWatchdog`(SYSTEM) 跑 `pythonw service_watchdog.py`
- ⚠️ async handler 禁同步耗时操作（upload_files/daily_check/sync_punch）→ `await asyncio.to_thread(...)`，否则 watchdog 判假死无限重启
- watchdog `HEALTH_FAIL_THRESHOLD=3`（连续 3 次约 45s 才重启）
- **重启用 `tools/restart_service_8765.py`**：netstat 找 PID → tasklist 校验 python.exe → `ctypes.windll.kernel32.TerminateProcess`（唯一可靠）。重启前核对 `data/scheduler_config.json` cron（09:00/16:00/16:30/03:00/00:00）避开当前时刻
- ⚠️ 应用日志在 `server.err.log`（stderr），`server.log` 只有 access log，两者均 **GBK 编码**
- ⚠️ `insurance_agent/infrastructure/database.py` **模块末尾有模块级 `init_db()`** → 任何 import 都对默认 DB_PATH 建表。写临时库脚本必须先改 `dbmod.DB_PATH` 再 import
- ⚠️ `netstat`/`tasklist` 输出 GBK → subprocess 读用 `encoding="mbcs", errors="replace"`；`wmic` Win11 24H2 已弃用

## 热重载与进程管理
- 节点代码：`POST /api/agent/reload` importlib.reload，无需重启
- ⚠️ server.py 改动必须重启；叶子层（pymupdf_parser/company_extractor/tools/filename_parser/date_parser）需在 `_reload_graph_dependencies` 注册
- ⚠️ 模块级 `from X import Y` reload 后仍指旧 class → 必须强杀进程

## Windows .bat 踩坑
- GBK 代码页：bat 写中文必须 ASCII（rem 注释除外）。换行检查用 `open(p,'rb').read().count(b'\r\n')`
- UAC 自提权：`net session >nul 2>&1` 失败 → `Start-Process -Verb RunAs`；mshta vbscript 不可靠
- 端口锁 PID 复用陷阱：`QueryFullProcessImageNameW` 验证指向 `\python.exe`/`\pythonw.exe`

## 测试环境
- 项目根 `.venv/Scripts/python.exe`（pytest+pymupdf）；`H-AGENT/.venv` 无 pytest
- 测试集：`tests/test_{shenyong,date_parser_timezone_prefix,dadi,change_endorsement,pingan_property}_*` + `test_inline_extractor_id_regex` + `test_yangguang_extraction`
- ⚠️ 脚本式测试别在顶层 `sys.exit()`（pytest INTERNALERROR），包 `if __name__=="__main__":`
- ⚠️ **写提取测试只喂 list_pages 文本，不喂全文**（条款"注册号"18 位被当身份证）
- 已知历史失败（缺模块）：test_llm_model、test_p6*_oss*、test_phase_b_memory、test_p5_recursive_tool_chain

## Bug 修复要点（可复用）
- **参数顺序错位**：SQL where 含 `policy_number=?` 但 params 错位 → SQLite 静默 rowcount=0。调试用 `db.get_connection()` 打印 rowcount
- **续页漏人**：大型清单续页省略表头 → `_is_list_continuation_page` 用 ≥3 身份证强证据
- **起止同天**：post_region 跨入下一个人 → 截到下个身份证号前
- **status 脏数据误发邮件**：normalize_person_status 白名单 + 排除式判断
- **NULL 期孤儿批单**：find_main_policy_by_company 第一个匹配错回旧保单 → 兼容性过滤
