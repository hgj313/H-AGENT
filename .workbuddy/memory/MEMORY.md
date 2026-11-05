# 保险单识别项目核心记忆

## 项目目标
从保险单 PDF 提取被保人员清单（姓名/证件号/所属公司/起止时间/保险公司/批改类型[增保/减保]）。保单号字段支持批单→主保单自动关联补全日期。

## 保险单格式速查（按保险公司）
| 保险公司 | 清单格式 | 逐人日期 | 用工单位 | 增减保 | 关键备注 |
|---|---|---|---|---|---|
| 利宝-保单/短期/批单/BD | table / inline | ❌整体 | ✅ | 纯增 | BD 文件名 `公司名_保单号_BD.pdf`；批单正文生效日描述两遍 |
| 太保(ASHH主/BSHH批) | table | ✅明细 / ❌清单 | 明细❌ 清单=投保人 | 纯增 | 安诚已归太保 |
| 华农-保单/批单 | table / inline | ❌ / ✅批改日 | ✅ | 纯增 / 增删 | |
| 中国人寿-在保名单 | **block_kv** | ✅逐人 | ✅「投保人」 | 增/减替 | BlockKVExtractor |
| 中国人寿-变动清单 | table 双栏 | ✅ | ✅ | 增/减/替 | 减栏无 ID→无法去失效 |
| 中国人寿财险-电子保单 | table | ❌整体 | ❌ | 纯增 | 跨行职业代码 `0702033-挖掘铲运和桩\n工机械司机` |
| 黄河-批单 | table 变动清单 | ✅ | ✅ | 增/删 | |
| 黄河-扫描件雇主责任险 | table OCR | ❌ | ✅"共同被保险人" | 主纯增/批增 | 全扫描件 OCR；"工种类"易误填 company |
| 华安-批单 | table | ✅ | ✅ | 增/删 | 续保批改；用工单位跨行 |
| 众安在线-非灵工 | table | ✅ | ✅ | 纯增 | 头词"人员名单"；PyMuPDF 拆身份证两行 |
| 众安灵工版 | no_list(不记名) | — | — | 总投 | |
| 北部湾-雇主责任险 | table | ❌整体 | 投保人=被保险人 | 纯增 | 标签"保险单号码"；工种在 ID 左、职业分类在 ID 右 |
| 平安产险-雇主安心保 | table | ❌整体 | 投保人=被保险人 | 纯增 | 20位保单号；职业+岗位双列；清单 P4-5 |
| 平安养老-PEAC | table | ❌整体 | 投保人=被保险人 | 增/删 | 起期/止期两条独立字段 |
| 阳光保险-HGC | table + inline 批单 | ❌ | 投保人=被保险人 | 增/减 | 批单英语标签 `End.NO.<batch>`/`PolicyNO.<main>` |
| 阳光《变更被保人》 | inline | ❌ | 投保人=被保险人 | 1减1增 | `姓名由X变更为Y` → `_extract_change` |
| 中国大地-PZFZ | table | ❌整体 | 投保人=被保险人 | 纯增 | 9页(9=清单)；销售单位=中介黑名单；身份证跨行 |
| 申能财产保险 | table | ❌整体 | 投保人=被保险人 | 纯增 | 条款含"注册号"假ID；期间"自北京时间…起至…止" |
| 平安-投保单 | no_list | — | — | — | 仅条款 |

## 关键识别规则
- **文件名含"投保单"≠投保申请书**：仅当同时无保单号且无清单页才判 `no_list`。
- **中介黑名单**：`保险经纪`/`代理公司`/`保险公估` → 跳 `parse_policy_filename`。
- **清单页定位**：`_LIST_MARKERS` → `_is_real_list_page`(表头词+6位数字) → 排除 `_is_clause_page`；续页 `_is_list_continuation_page`(≥3 身份证，含脱敏)。
- **`_is_real_list_page` header 收紧**：主判据"姓名/雇员姓名"；无姓名但含"证件号"且不含"统一社会信用代码"才兜底。
- **table_extractor post_region 双重截断**：① 截到下个身份证号前；② 截到 `\n\n` 前（**PDF 页边界**，防跨页抓页脚）。
- **table_extractor 工种 post 优先 + "建筑工"排除**；⚠️ 不能改 pre 优先（混入前一人 post 数据 + 表头"用工单位"）。
- **PyMuPDF 身份证跨行**：`510223197311+103531` 拆两行 → `re.sub` 跨行拼接（众安/大地/申能都中招）。
- **保单号标签**：`保险单号码?` 兼容多"码"字。
- **日期空格**：`2026 年 10 月 01 日` → date_parser 年/月/日两侧加 `\s*`。
- **工种字段分离（10-8）**：`_OCCUPATION_CLASS_PATTERN`→`occupation_class`；`_JOB_PATTERN`→`job_title`（带中文括号后缀）；job_title 空退化 occupation_class。
- **跨行工种合并（4b）**：`X类职业\n工种` 贪婪合并错误 → 合并前"职业"后插 `\ue000`（U+E000），合并后还原。⚠️ 不能用 `\x00`（re.sub 当转义）；占位符必须放"职业"**之后**。
- **利宝批单生效日重复（11-03）**：正文同一生效日写两遍（"批单生效日期 自X起生效" + "兹经双方同意,自X起…批改"）→ pre_region 回溯吃进两处 → 起止同天=减保特征，增保人员误判。修复 `_strip_zero_count_remove_markers`（剔除"减少0人"汇总句）+ `_is_repeated_effective_date`（起止同天且重复描述→清空交由 validator 按主保单回填）。

## date_parser 整体期间格式矩阵
- 「自X起至Y止」：`自(\d{4})年(\d{1,2})月(\d{1,2})日…起…至…止`（日期间允许任意中文+数字+时间词）。
- 「自北京时间X起至Y止」：⚠️ "自"与年份间可能插时区口径词（北京时间/当地时间/世界时/标准时）→ `_TIMEZONE_PREFIX` 可选前缀 + 回归测试 `test_date_parser_timezone_prefix.py`。
- 「保险起期（北京时间）：X 保险止期（北京时间）：Y」：两条独立字段（平安养老）。
- block_kv 双字段：「保险合同生效日期/满期日期」顺序不固定 → 取 min/max。

## 身份证脱敏 ID 四种格式
| 格式 | 样例 | 来源 |
|---|---|---|
| 完整 18 位 | `110101199001011234` | 多数保单 |
| 6+8+4 | `412702********2432` | 平安养老 PEAC |
| 14+4 | `51102519741110****` | 平安产险 / 申能财险 |
| 通用正则 | `(?:\d{6}\*{6,10}\d{0,4}[\dXx]?\|\d{14}\*{4})` | inline/metadata |

- 校验进 `_MASKED_ID_PATTERN_TAIL`（仅校验地区码前缀）；**保留 * 号入库，不反推**（用户指令）。
- ⚠️ **扩展正则必须写回归测试覆盖旧+新+混合**。教训：`inline_extractor._ID_REGEX`（9-24 改脱敏后旧格式全 0 人）、`date_parser._OVERALL_PATTERNS`（9-28 时区词）。
- ⚠️ **脱敏 ID 导致"打卡无正常保单"误报（10-28）**：PDF 证件号脱敏、打卡完整 18 位 → 等值比对失败 → 误判未参保误发邮件。**用户决策：不改代码，走人工补全**（`data/待人工补全身份证号清单.csv` + `tools/fill_masked_id_numbers.py --apply`）。曾做掩码匹配器被要求回滚——同类问题先问。

## 技术方案
PDF：PyMuPDF 文字层 + 扫描件 MiniMax-M3 视觉 OCR。LangGraph：policy_parser → metadata_extractor → personnel_extractor → validator → output。Extractors：table/inline/individual/block_kv/ocr。LLM：MiniMax-M3（Anthropic 协议，H-AGENT/.env）。服务：FastAPI（web_app/server.py :8765）+ service_watchdog.py。

## 关键设计
- **批单→主保单关联（L1+L2+L3）**：L1 validator `_link_to_main_policy` 按 `main_policy_number` 查主表，不匹配按 `_policy_numbers_compatible` 前缀兼容（利宝批单 71XX vs 主保单 81XX）；L2 `policy_library` 兜底；L3 主保单缺失直接 return error。
- **保单库双表**：`policy_library.register()` 按 policy_type 分流 `index_main.json`/`index_batch.json`。
- **ExtractionResult 字段透传**：`batch_policy_number`/`main_policy_number`/`policy_type`/`endorsement_effective_date`。
- **公司识别 3 层**：L1 `_COMPANY_PATTERNS` 长关键词优先 → L2 命中次数加权 → L3 `detect_insurance_company_by_policy_number` 号段兜底（最强）。已注册号段：613010104=华安 / 81160=利宝 / 81160&61160=安诚 / ASHH,BSHH,X44,SHBX=太保 / 804147=北部湾 / PEAC=平安养老 / PZFZ=大地 / 6513=申能。

## 数据库与去重
- 表 `insurance_personnel`；判重键 `(name, id_number)`；**partial UNIQUE INDEX `idx_person_name_id_uniq ON (name,id_number) WHERE id_number != ''`（11-05 重建，一��一行）**。含 name → 脱敏 ID 撞车的不同人仍可共存（10-27 教训）。
- ⚠️ **11-05 业务规则变更**：原「同人跨保单多条记录=合法续保轨迹」的判断**已被推翻** —— 用户定「同一姓名同一身份证号只保留一条」。这一条正是「本地未参保 11 人 vs 飞书 22 人」统计失真的根因。
- **写侧去重（11-05，用户原话）**：「新入库的如果原数据库中存在且起止日期更久的，替换原数据。不然不需要新增。避免出现重复数据」
  - 入口 `upsert_insurance_personnel_detailed()` → 返回 `{written,added,updated,collapsed,skipped,details}`；`upsert_insurance_personnel()` 是薄封装（返回 int）；`add_insurance_personnel()` 复用同一规则。
  - 判定 `_decide_replace()`：①新数据排序键更大（止期更晚→起期更晚）→替换 ②更小→跳过，**例外**：旧记录止期未知(空)且新数据仍在有效期内→替换 ③完全等价→仅当新数据能补齐旧记录空字段才替换。
  - 排序键 `_personnel_rank()` = `(end_date, start_date, status有效, policy_number非空, id)`，空日期=`9999-12-31`。⚠️ **比较「新 vs 旧」时必须只取前 4 项（不含 id）**，否则库中已有行因 id 更大而永远赢过新数据。
  - ⚠️ 与离线工具 `sort_key=(start_date,end_date,...)` 顺序不同是有意的：end 优先更安全（避免选中「起期更晚但止期更早」的短区间把在保人员降级）。218 组实测两者结果 0 分歧。
  - **日期保护**：新数据日期为空时保留原记录日期（不覆盖）→ 避免在保人员被误降为失效（11-03 踩过）。
  - **收敛历史重复**：库中已有该人多条时，替换前先吸收其余行非空字段，再删其余行 → 一人一行。
  - 旧机制 `ON CONFLICT(name,id_number,policy_number)` 已废除 —— 保单号不同会走 INSERT 新增，正是重复数据再生源头。
- **status 白名单** `db.normalize_person_status()`（正常/失效/增保/减保/替换…）。
- `deactivate_insurance(ids, end_date, main_policy_number)` — 加参数必须 grep 所有调用点。
- ⚠️ 跑 web_app.server 必须用 **`H-AGENT/.venv/Scripts/python.exe`**（有 fastapi/pymupdf/langchain），项目根 `.venv` 缺这些。
- **去重工具 `tools/dedupe_insurance_personnel.py`**：同名同身份证只保留起止日期偏后一条。dry-run 默认，`--apply` 执行（快照+逐人校验+失败回滚）。保留排序键取最大值 `recs[-1]`：`start_date→end_date→status有效>失效→policy_number非空→id`，空日期=`9999-12-31`。⚠️ 字段合并**绝不能含 start_date/end_date**（3 人翻转教训）；⚠️ UNIQUE(name,id,policy) 合并 policy_number 会冲突 → **先 DELETE 再 UPDATE**；⚠️ 去重后逐人比对参保状态翻转。

## 数据安全（11-03 加固）
- **快照** `insurance_agent/tools/db_snapshot.py` → `data/snapshots/`，用 `Connection.backup()` 在线备份（**不能直接拷文件**，WAL 未同步）。定时 `daily_snapshot`（03:00，保留 30 天）。
- **替换接口三道防线**（`/api/personnel/upload-excel` = **替换**，先 `clear_insurance_personnel()` 清空全表）：① 必须 `?confirm=true` ② 清空前自动快照 ③ Excel 条数 < 库中 30% 拒绝。`upload-excel-add` = **追加**（安全）。⚠️ 操作前务必确认按钮。
- **快照回滚 API**：`GET /api/db/snapshots` / `POST /api/db/snapshot` / `POST /api/db/restore?name=&confirm=true`（路径穿越防护）。
- ⚠️ FastAPI 路由 `request: Request` 必须放在无默认值参数之前。

## ERP / MQ / 短信
- page_size：fetch_all_punch_data=500、fetch_project_orders=500、fetch_user_list=1000。
- MQ：topic=`JS_PROD_MQ`、group=`insurance-automation`；endpoint 带 `-public` 后缀；group 与 ERP 隔离（GID_INSURANCE_AGENT_PROCESS）。
- **双 dedup**：`last_daily_check.punch_date`（force 可绕）+ `daily_sms_sent_today.phones`（force 不可绕）。
- ⚠️ **通知安全规则**：`/api/summary/trigger?force=true`、`/api/reminder/check-expiry`、`/api/daily-check?force=true`、改 `notification_test_mode` 前**必须问用户**；例外=scheduler 定时任务。
- 双开关勿混：A=`punch_table_for_sms`（数据源），B=`notification_test_mode`（通知路由）。

## 服务稳定性
- 8765 **仅 127.0.0.1 监听**，无公网。本地常驻：计划任务 `InsuranceAgentWatchdog`（SYSTEM）跑 `pythonw service_watchdog.py`。
- ⚠️ **async handler 禁同步耗时操作**（upload_files/daily_check/sync_punch）→ `await asyncio.to_thread(...)`，否则阻塞事件循环 → watchdog 判假死无限重启。
- watchdog `HEALTH_FAIL_THRESHOLD=3`（连续 3 次约 45s 才重启）。
- **重启服务用 `tools/restart_service_8765.py`**（11-05 新增）：netstat 找 8765 的 PID → tasklist 校验是 python.exe（防 PID 复用误杀）→ `ctypes.windll.kernel32.TerminateProcess` 终止 → watchdog 检测 `proc.poll()` 崩溃后自动拉起（实测 ~17s）。重启前先核对 `data/scheduler_config.json` 的 cron 时间（09:00/16:00/16:30/03:00/00:00）避开当前时刻，否则可能触发通知任务。
- ⚠️ **应用日志在 `server.err.log` 不是 `server.log`**：`logging.StreamHandler()` 不带参数写 **stderr**（server.py 注释写 stdout 是不准确的）。`server.log` 只有 uvicorn access log。两者均 **GBK 编码**，grep 中文会乱码。
- ⚠️ **`insurance_agent/infrastructure/database.py` 模块末尾有模块级 `init_db()`** → 任何 `import` 都会对**默认 DB_PATH** 执行建表/建索引。写临时库脚本时必须先改 `dbmod.DB_PATH` 再 import，否则迁移会打到线上库。
- ⚠️ `netstat`/`tasklist` 输出是 GBK → subprocess 读要用 `encoding="mbcs", errors="replace"`；`wmic` 在 Win11 24H2 已弃用。

## 热重载与进程管理
- 节点代码：`POST /api/agent/reload` importlib.reload，无需重启。
- ⚠️ **server.py 改动必须重启**；叶子层（pymupdf_parser/company_extractor/tools/filename_parser/date_parser）需在 `_reload_graph_dependencies` 注册。
- ⚠️ **模块级 `from X import Y` reload 后仍指旧 class** → 必须强杀进程让 watchdog 重启。
- ⚠️ **杀进程唯一可靠**：`ctypes.windll.kernel32.TerminateProcess(handle, 1)`（Stop-Process/taskkill 可能 exit 1 但未终止）。

## Windows .bat 踩坑
- GBK 代码页：bat 写中文必须 ASCII（rem 注释除外）。换行检查用 Python 二进制 `open(p,'rb').read().count(b'\r\n')`。
- UAC 自提权：`net session >nul 2>&1` 失败 → `Start-Process -Verb RunAs`；mshta vbscript 不可靠（沙箱无桌面永久挂起）。
- 端口锁 PID 复用陷阱：`QueryFullProcessImageNameW` 验证指向 `\python.exe`/`\pythonw.exe`。鉴权用客户端 IP 别用 Host 头。

## 测试环境
- 解释器：项目根 `.venv/Scripts/python.exe`（pytest+pymupdf）；`H-AGENT/.venv` 无 pytest。
- 测试集：`tests/test_{shenyong,date_parser_timezone_prefix,dadi,change_endorsement,pingan_property}_*` + `test_inline_extractor_id_regex` + `test_yangguang_extraction`（27 passed）。
- ⚠️ 脚本式测试别在顶层 `sys.exit()`（pytest INTERNALERROR），必须包 `if __name__=="__main__":`。
- ⚠️ **写提取测试只喂 list_pages 文本，不喂全文**（条款"注册号"18 位被当身份证）。
- 已知历史失败（缺模块，与提取无关）：test_llm_model、test_p6*_oss*、test_phase_b_memory、test_p5_recursive_tool_chain。

## Bug 修复要点（有复用价值）
- **参数顺序错位（9-16）**：SQL `where_sql` 含 `policy_number=?` 但 params 错位 → SQLite 静默 rowcount=0。调试用 `db.get_connection()` + 打印 rowcount。
- **续页漏人（9-14）**：大型清单续页省略表头 → `_is_list_continuation_page` 用 ≥3 身份证强证据。
- **起止同天（9-14）**：post_region 跨入下一个人 → 截到下个身份证号前。
- **段小平 company 误识"黄河"（9-16）**：华安缺 pattern + 首次命中无加权 → 3 层修复。
- **status 脏数据误发邮件（9-16）**：normalize_person_status 白名单 + get_active_insurance_by_id 排除式判断。
- **NULL 期孤儿批单（9-18）**：find_main_policy_by_company 第一个匹配错回旧保单 → 改 `_find_main_policy_by_company_compatible` 兼容性过滤。
- **job_title 被 occupation_class 吞（10-8）**：双列格式岗位丢失 → 拆两字段。
- **整体期间时区词致日期全 NULL（9-28）**：`自北京时间2026年...` → `_TIMEZONE_PREFIX` 可选前缀。
