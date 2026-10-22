# 保险单识别项目核心记忆

## 项目目标
从各种保险单 PDF 提取被保人员清单（姓名/证件号/所属公司/起始时间/起止时间/保险公司/批改类型[增保/减保]）。保单号字段需支持批单→主保单自动关联补全日期。

## 保险单格式速查（按保险公司）
| 保险公司 | 清单格式 | 逐人日期 | 用工单位 | 增减保 | 关键备注 |
|---|---|---|---|---|---|
| 利宝-保单/短期/批单/BD | table / inline | ❌整体 | ✅ | 纯增 | 短期单"生效日期"列易触发 post_region 跨行 bug；BD 文件名 `公司名_保单号_BD.pdf` |
| 太保(ASHH主/BSHH批) | table | ✅明细表 / ❌人员清单 | 明细❌ 清单=投保人 | 纯增 | 安诚已归太保(9-16 修正) |
| 华农-保单/批单 | table / inline | ❌ / ✅批改日 | ✅ | 纯增 / 增删 | |
| 中国人寿-在保名单 | **block_kv** | ✅逐人 | ✅「投保人」标签 | 增/减替 | BlockKVExtractor |
| 中国人寿-变动清单 | table 双栏 | ✅ | ✅ | 增/减/替 | 「同期增减」减栏无 ID→无法去失效 |
| 中国人寿财险-电子保单 | table | ❌整体 | ❌ | 纯增 | 25 页；`0702033-挖掘铲运和桩\n工机械司机` 跨行职业代码→`_OCCUPATION_CODE_PATTERN` |
| 国寿(其他)/人保关爱保个人 | table / individual | ❌ | ❌ | 纯增 | |
| 黄河-批单 | table 变动清单 | ✅ | ✅ | 增/删 | |
| 黄河-扫描件雇主责任险 | table OCR | ❌ | ✅"共同被保险人" | 主纯增/批=增 | 全扫描件 OCR；"工种类"易误填 company→`_looks_like_company_name` 兜底 |
| 华安-批单 | table | ✅ | ✅ | 增/删 | 续保批改(P1 全 + P21-22 末尾页)；用工单位跨行 |
| 众安在线-非灵工 | table | ✅ | ✅ | 纯增 | 头词"人员名单"(非"清单")；PyMuPDF 拆身份证成两行 |
| 众安灵工版 | no_list(不记名) | — | — | 总投 | |
| 北部湾-雇主责任险 | table | ❌整体 | 投保人=被保险人 | 纯增 | 标签"保险单号码"(多"码"字)；职务·工种在 ID **左**，职业分类路径在 ID **右** |
| 平安产险-雇主安心保-四川 | table | ❌整体 | 投保人=被保险人 | 纯增 | 20 位保单号；职业类别+岗位名称双列；清单在 P4-5 |
| 平安养老-PEAC | table | ❌整体 | 投保人=被保险人 | 增/删 | 期间是"保险起期(北京时间)+保险止期"两条独立字段 |
| 阳光保险-HGC | table + inline 批单 | ❌整体/❌批单生效日 | 投保人=被保险人 | 增/减 | 批单用英语标签 `End.NO.<batch>`/`PolicyNO.<main>`；工种带中文括号后缀 |
| 阳光保险《变更被保人》 | inline | ❌批单生效日 | 投保人=被保险人 | 1减+1增 | `姓名由X变更为Y,证件号码由A变更为B` → `_extract_change` |
| 中国大地财产保险-PZFZ | table | ❌整体 | 投保人=被保险人 | 纯增 | 9 页(9=雇员清单)；销售单位=中介被黑名单跳过；身份证跨行 |
| 申能财产保险 | table | ❌整体 | 投保人=被保险人 | 纯增 | 11 页(2-3=雇员清单，4/10/11=条款含"注册号"假 ID)；期间"自**北京时间**…起至…止" |
| 平安-投保单 | no_list | — | — | — | 仅条款 |

## 关键识别规则
- **文件名含"投保单"≠投保申请书**：仅当同时无保单号且无清单页才判 `no_list`。
- **中介公司黑名单**：`保险经纪`/`代理公司`/`保险公估` → 跳到 `parse_policy_filename`。
- **清单页定位**：`_LIST_MARKERS` → `_is_real_list_page`(表头词+6位数字) → 排除 `_is_clause_page`；续页 `_is_list_continuation_page`(≥3 个身份证，含脱敏) 作强证据。
- **`_is_real_list_page` header 收紧**：主判据"姓名/雇员姓名"；无姓名但含"证件号"且不含"统一社会信用代码"才兜底。
- **table_extractor post_region 双重截断**：① 截到下个身份证号前（防 next-person 日期）；② 截到 `\n\n` 前（**\n\n 是 PDF 页边界**，防跨页抓到页脚/条款当工种）。
- **table_extractor 工种 post 优先 + "建筑工"排除**：排除"建筑工程"路径里的"建筑工"。⚠️ 不能改 pre 优先（会混入前一人 post 数据 + 表头"用工单位"）。
- **PyMuPDF 身份证跨行**：常把身份证拆成两行（510223197311+103531）→ `re.sub` 跨行拼接（众安/中国大地/申能都中招）。
- **保单号标签**：`保险单号码?` 兼容多"码"字。
- **日期空格**：`2026 年 10 月 01 日` → date_parser 在年/月/日两侧加 `\s*`。

## date_parser 整体期间格式矩阵（关键）
- 「自X起至Y止」：`自(\d{4})年(\d{1,2})月(\d{1,2})日…起…至…止`（日期间允许任意中文+数字+时间词）
- 「自北京时间X起至Y止」：⚠️ **"自"与年份之间可能插入时区口径词**（北京时间/当地时间/世界时/标准时）。旧正则要求"自"后紧跟数字 → 申能保单整体期间解析返回 (None,None) → 9 人日期全 NULL。修复：`_TIMEZONE_PREFIX` 可选前缀 + **必配回归测试**（test_date_parser_timezone_prefix.py）。
- 「保险起期（北京时间）：X 保险止期（北京时间）：Y」：两条独立字段（平安养老）；括号可有可无。
- block_kv 双字段：「保险合同生效日期/满期日期」（中国人寿在保名单，顺序不固定 → 取 min/max）。

## 身份证脱敏 ID 四种格式
| 格式 | 样例 | 来源 |
|---|---|---|
| 完整 18 位 | `110101199001011234` | 多数保单 |
| 6+8+4 | `412702********2432` | 平安养老 PEAC |
| 14+4 | `51102519741110****` | 平安产险 / 申能财险 |
| 通用正则 | `(?:\d{6}\*{6,10}\d{0,4}[\dXx]?\|\d{14}\*{4})` | inline_extractor / metadata_extractor_node |

- 校验都进 `_MASKED_ID_PATTERN_TAIL` 分支（仅校验地区码前缀）；**保留 * 号入库，不反推**（用户明确指令）。
- ⚠️ **扩展正则必须写回归测试覆盖旧+新+混合**，否则易回归。两次教训：`inline_extractor._ID_REGEX`（9-24 改脱敏后旧格式全 0 人）、`date_parser._OVERALL_PATTERNS`（9-28 加时区词前要求"自"后紧跟数字）。

## table_extractor 工种字段分离（10-8）
1. `_OCCUPATION_CLASS_PATTERN` 命中 → `occupation_class` 字段（不再吞掉 job_title）
2. `_JOB_PATTERN` 继续匹配 → `job_title`（工种带中文括号后缀，如 `水电工（非涉高）`）
3. `job_title` 空时退化到 `occupation_class`（兼容只有职业类别列的格式）
- `_OCCUPATION_CODE_PATTERN`（GB/T 6565 七位数字代码）也走 `occupation_class`。

## 跨行工种合并（4b）+ 占位符保护
规则 `X类职业\n工种` 会被贪婪合并成错误结果（如"三类职业绿化栽植工"）。修复：合并前先把"职业"后插入 `\ue000`（U+E000 私有区字符），合并后还原。
- ⚠️ 不能用 `\x00`（re.sub replacement 会当 regex 转义解析报错），必须用 lambda 注入。
- ⚠️ 占位符必须放"职业"**之后**而非中间，否则前段"业"+"\n"+后段仍匹配。

## 技术方案
- PDF：PyMuPDF 文字层 + 扫描件 MiniMax-M3 视觉 OCR
- LangGraph：policy_parser → metadata_extractor → personnel_extractor → validator → output
- Extractors：table / inline / individual / block_kv / ocr
- LLM：MiniMax-M3（Anthropic 协议，H-AGENT/.env）
- 服务：FastAPI（web_app/server.py :8765）+ service_watchdog.py

## 关键设计
- **批单→主保单关联（L1+L2+L3）**：L1 validator `_link_to_main_policy` 用 `main_policy_number` 查主表，不匹配时按 `_policy_numbers_compatible` 前缀兼容（利宝批单 71XX vs 主保单 81XX）；L2 `policy_library` 兜底；L3 上传时主保单缺失直接 return error。
- **保单库双表**：`policy_library.register()` 按 policy_type 分流 `index_main.json` / `index_batch.json`。
- **ExtractionResult 字段透传**：`batch_policy_number` / `main_policy_number` / `policy_type` / `endorsement_effective_date`。
- **公司识别 3 层**：L1 `_COMPANY_PATTERNS` 长关键词优先 → L2 按命中次数加权 → L3 `detect_insurance_company_by_policy_number` 号段兜底（号段=承保机构硬证据，最强）。已注册号段见 `company_extractor._POLICY_NUMBER_PREFIX_TO_COMPANY`（613010104=华安 / 81160=利宝 / 81160&61160=安诚 / ASHH,BSHH,X44,SHBX=太保 / 804147=北部湾 / PEAC=平安养老 / PZFZ=大地 / 6513=申能）。

## 数据库与去重
- 表 `insurance_personnel`；判重键 `(name, id_number)` + partial unique index `WHERE id_number != ''`
- ⚠️ `idx_person_name_id` UNIQUE INDEX 已删除（同人跨保单合理）。
- **upsert 保险型覆盖规则**：`WHERE (end_date='' OR excluded.end_date='' OR excluded.end_date >= COALESCE(insurance_personnel.end_date,'1900-01-01'))` — 空 end_date 视为可被任何新值覆盖。
- **status 白名单**：`db.normalize_person_status()`（正常/失效/增保/减保/替换…），未知值按 end_date 推断；否则会误判未参保 → 误发邮件。
- `deactivate_insurance(ids, end_date, main_policy_number)` — 加参数时必须 grep 所有调用点。

## ERP / MQ / 短信
- page_size：fetch_all_punch_data=500、fetch_project_orders=500、fetch_user_list=1000
- MQ：topic=`JS_PROD_MQ`、group=`insurance-automation`；endpoint 必须带 `-public` 后缀；group 与 ERP 隔离（GID_INSURANCE_AGENT_PROCESS）
- **双 dedup**：`last_daily_check.punch_date`（force 可绕）+ `daily_sms_sent_today.phones`（force 不可绕）
- ⚠️ **通知发送安全规则**：`/api/summary/trigger?force=true`、`/api/reminder/check-expiry`、`/api/daily-check?force=true`、改 `notification_test_mode` 前**必须问用户**；唯一例外=scheduler 定时任务。
- 生产/测试双开关勿混淆：A=`punch_table_for_sms`（数据来源），B=`notification_test_mode`（通知路由）。

## 服务稳定性
- 8765 **仅本机 127.0.0.1 监听**，无公网
- 本地常驻：计划任务 `InsuranceAgentWatchdog`（SYSTEM 身份开机自启）跑 `pythonw service_watchdog.py`
- ⚠️ **async handler 里禁止同步调耗时操作**（upload_files / daily_check / sync_punch）→ 用 `await asyncio.to_thread(...)`，否则阻塞 uvicorn 事件循环 → watchdog 判假死 → 无限重启循环
- watchdog `HEALTH_FAIL_THRESHOLD=3`（连续 3 次约 45s 才重启）

## 热重载与进程管理
- 节点代码（nodes/*）：`POST /api/agent/reload` 用 importlib.reload 重载，无需重启
- ⚠️ **server.py 自身改动必须重启服务**；叶子层（pymupdf_parser/company_extractor/tools/filename_parser/date_parser）需在 `_reload_graph_dependencies` 注册
- ⚠️ **模块级 `from X import Y` reload 后仍指向旧 class object** → 必须强杀进程让 watchdog 重启
- ⚠️ **杀进程唯一可靠方式**：`ctypes.windll.kernel32.TerminateProcess(handle, 1)`。`Stop-Process` / `taskkill /F /T` 某些场景返回 exit 1 但进程未终止。

## Windows .bat 踩坑
- 用户系统 GBK 代码页：bat 写中文必须 ASCII（rem 注释除外）
- 检查换行用 Python 二进制：`open(p,'rb').read().count(b'\r\n')`
- UAC 自提权：`net session >nul 2>&1` 失败 → `Start-Process -Verb RunAs`；mshta vbscript 自提权不可靠（沙箱无桌面会永久挂起）
- 端口锁 PID 复用陷阱：`QueryFullProcessImageNameW` 验证 PID 指向 `\python.exe`/`\pythonw.exe`
- 鉴权用客户端 IP（`_client_ip`）别用 Host 头

## 测试环境
- 可用解释器：项目根 `.venv/Scripts/python.exe`（有 pytest + pymupdf）；`H-AGENT/.venv` **无 pytest**，系统 python 也无
- 保险测试集：`tests/test_{shenyong,date_parser_timezone_prefix,dadi,change_endorsement,pingan_property}_*.py` + `test_inline_extractor_id_regex` + `test_yangguang_extraction`（27 passed）
- ⚠️ **脚本式测试不要在模块顶层 `sys.exit()`** → pytest 收集时 INTERNALERROR。必须包 `if __name__ == "__main__":`
- ⚠️ **写提取测试只喂 list_pages 文本，不要喂全文** → 条款页"注册号：6230912026..."等 18 位数字会被当身份证（申能保单实测多出 3 个 name='注册号' 垃圾人）
- 已知历史失败（与提取无关，缺模块）：`tests/test_llm_model`、`test_p6*_oss*`、`test_phase_b_memory`、`test_p5_recursive_tool_chain`

## Bug 修复要点（只留有复用价值的）
- **参数顺序错位隐性炸弹（9-16）**：SQL `where_sql` 含 `policy_number=?` 但 params 拼错位置，SQLite **静默返回 rowcount=0**。调试必须用 `db.get_connection()` 复现 + 打印 rowcount。
- **续页漏人（>100人，9-14）**：大型清单续页常省略表头 → `_is_list_continuation_page` 用「≥3 个身份证」作强证据。
- **起止同天（9-14）**：post_region 跨入下一个人 → 截到下个身份证号前。
- **段小平 company 误识"黄河"（9-16）**：`华安` 缺 pattern + 首次命中无加权 → 3 层修复（补 pattern / 加权 / 号段兜底）。
- **status 脏数据误发邮件（9-16）**：`status='增保'` 未归一 → 连续 3 天误发"未参保"。修复：`normalize_person_status` 白名单 + `get_active_insurance_by_id` 排除式判断。
- **NULL 期孤儿批单（9-18）**：`find_main_policy_by_company` 第一个匹配错回旧保单 → 改 `find_main_policy_by_company_compatible` 按兼容性过滤。
- **脱敏 ID 校验（9-24 / 10-8）**：平安养老 6+8+4、平安产险/申能 14+4 三种格式统一进 `_MASKED_ID_PATTERN_TAIL` 分支。
- **job_title 被 occupation_class 吞掉（10-8）**：双列格式下岗位名丢失 → 拆两个字段。
- **跨行工种合并误吞（10-8）**：`X类职业\n工种` 贪婪合并 → `\ue000` 占位符保护。
- **整体期间时区词致日期全 NULL（9-28）**：`自北京时间2026年...` → `_TIMEZONE_PREFIX` 可选前缀。