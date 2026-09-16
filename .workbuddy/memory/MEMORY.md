# 保险单识别项目记忆

## 项目目标
从各种保险单PDF提取被保人员清单（姓名/证件号/所属公司/起始时间/起止时间/保险公司/批改类型[增保/减保]）。

## 保险单格式速查表（提取策略）
| 保险公司 | 清单格式 | 逐人日期 | 用工单位 | 增减保 | 备注 |
|----------|---------|---------|---------|--------|------|
| 利宝保险-保单 | table(序号/雇员姓名/证件号/性别/年龄/职业/用工单位) | ❌整体期限 | ✅有列 | 纯增保 | |
| 利宝保险-保单（短期 1-3 月期） | table(序号/雇员姓名/证件类型/证件号/性别/年龄/职业/等级/计划/保费/用工单位/**生效日期**) | ❌整体期限（单"生效日期"列） | ✅有列 | 纯增保 | **2026-09 新发现子格式**：只有"生效日期"一列，**无**独立的"止期"列；**全员同一起保日**时易触发 table_extractor 的 post_region 跨行 bug 导致 end_date 误填成下一个人的生效日期。已修复：post_region 截断到下一个身份证号之前 |
| 利宝保险-批单 | inline(雇员姓名：XX，证件号：XX，用工单位：XX) | ❌批单生效日 | ✅行内 | 纯增保 | **无逐人日期，需关联主保单期间补全** |
| 利宝保险-BD格式 | 公司名_保单号_BD.pdf（不带前缀） | 靠保单号首字符判断（8=主保单, 7=批单） | ✅ | 增/减 | BD格式 filename_parser 必须支持 |
| 中国太平洋财险-明细表 | table(序号/姓名/证件号/岗位名称/起期/止期) | ✅逐人 | ❌投保人获取 | 纯增保 | |
| 中国太平洋财险-人员清单 | table(工种/人员姓名/证件类型/证件号/限额/雇佣性质) | ❌整体期限 | ❌投保人 | 纯增保 | **无序号/无逐人日期**，用工单位=投保人 |
| 华农财险-保单 | table(保险方案/序号/姓名/证件号/出生日期/职业工种/等级/用工单位/地点) | ❌整体期限 | ✅ | 纯增保 | |
| 粤灿批单(华农) | inline(证件号:标签) | ✅批改生效日 | ✅ | 增/删 | |
| 中国人寿财险 | table(序号/姓名/身份证号/职业类别) | ❌整体期限 | ❌ | 纯增保 | |
| 人保"关爱保"个人 | individual(被保险人信息键值对) | ❌整体期限 | ❌ | 纯增保 | |
| 众安灵工版 | no_list(不记名/总人数) | — | — | 总投保 | |
| 黄河财险-批单 | table(雇员变动清单) | ✅批改生效日 | ✅ | 增/删 | |
| **华安财产保险-批单** | table(序号/方案/姓名/证件类型/证件号码/岗位/用工单位/职业小类/职业等级/备注/保险生效起期/保险生效止期/批改时间) | ✅逐人（保单期内同日期） | ✅ | 增/删 | **2026-09 新增**：保单号前缀 `613010104` 是华安号段；批改单 P1 列出全部延续人员（续保批改模式），实际入库仅新增/变更人员（P21-22 末尾页）；用工单位跨行（"杭州班王\n建筑劳务\n有限公司\n重庆分公司"），依赖续页断点检测 |
| 平安财险-投保单 | no_list(仅条款) | — | — | — | |
| 安诚财险(ASHH/81160131) | table(投保人名称 空格分隔) | ❌整体期限 | 投保人 | 纯增保 | |
| **众安在线财险（非灵工）** | table(序号/姓名/性别/证件号码/职业代码/保险方案/实际用人单位/实际用工企业/保障起期/保障止期/人均保费) | ✅逐人 | ✅有列 | 纯增保 | **2026-09 新增**：表头关键词是"人员名单"（不是"人员清单"），PyMuPDF 可能把 18 位身份证拆成两行（如 `43061119711230\n2016`），靠 `re.sub(r'(\d{3,})\n(\d\|[Xx])', r'\1\2', text)` 跨行拼接；前几页条款页常含"雇员清单"会触发误识别 → 用 `_is_clause_page` + `_is_real_list_page` 双过滤 |

## 关键识别规则（易错点）
- **文件名含"投保单" ≠ 投保申请书**：仅当同时无保单号且无清单页才判 `no_list`。例"逸趣投保单.pdf"实为保险单。
- **投保人公司名提取**：`投保人`标签必须紧跟冒号；`投保人名称`/`名称`标签支持空格分隔。
- **中介公司黑名单**：跳过 `广东美保保险经纪` / `保险经纪` / `代理公司` / `保险公估` — 这些是代为投保的中介。识别时拦截 → 回退到 `parse_policy_filename` 从文件名 `保单_<公司>_<保单号>.pdf` 提取。
- **工种跨行合并**：排除"是/否"等雇佣性质取值，避免"是石工"误合并；2字工种(石工/焊工)需支持。
- **利宝批单起止日期缺失**：inline 格式只有"批单生效日期"（=主保单起期），无逐人日期 → 用主保单 start/end_date 给批单记录 UPDATE。
- **BD格式文件名**：`公司名_保单号_BD.pdf` 不带"批单"/"保单"前缀 → `filename_parser` 必须支持，正则 `^(.+?)_(\d{16,30})_BD$`。
- **清单页定位（精确版）**：`_LIST_MARKERS` 命中后，必须用 `_is_real_list_page`(表头词+6位数字) 真清单校验，再用 `_is_clause_page`(条款/附录/赔偿处理) 剔除误触发；跨页扩展的续页判定**不能用表头词作为唯一条件**——大型保单（>100 人）常省略重复表头，需用 `_is_list_continuation_page()`（≥3 个 18 位身份证）作为续页强证据。
- **table_extractor post_region 截断（2026-09-14 关键）**：`post_region = list_text[id_pos:id_pos + 400]` 必须截断到下一个身份证号之前。否则会把"下一个人员的生效日期"误当作"当前人员的起止日期"——当所有人员同一起保日（利宝 1-3 月期短期保单常见）时，会导致 end_date == start_date（同一天）。修复后单列"生效日期" + 全员同日期场景稳定。

## 技术方案
- PDF解析: PyMuPDF 文字层 + 扫描件 MiniMax-M3 视觉OCR
- 流程: policy_parser→metadata_extractor→personnel_extractor→validator→output (LangGraph)
- Extractors: table / inline / individual / ocr（按 format_hint 分发）
- LLM: MiniMax-M3 (Anthropic协议，H-AGENT/.env)
- 服务: FastAPI (web_app/server.py :8765) + watchdog (service_watchdog.py) + 一键启动服务.bat

- **批单关联主保单 fallback bug（2026-09-15 已修，3 层防御 ✅）**：根因 + 修复见下方「关键 Bug 修复要点」最新条目。3 层防御：
  1. **validator 层** (`validator_node._link_to_main_policy`)：`main_policy.policy_number == policy_number` 相等校验，不匹配拒绝补全日期 + warning
  2. **policy_library 层** (`_policy_numbers_compatible`)：保单号前缀兼容校验（利宝：批单 71XX 与主保单 81XX 中间 18 位相同 + 第 2 位一致），兜底防 validator 漏网
  3. **上传入口层** (`_process_single_pdf`)：批单主保单缺失/不匹配时直接 return error，阻断脏数据入库
- **upsert 拒绝覆盖导致新正确数据不写库（同日衍生，2026-09-15）**：批单004 (减 谭建芬/增 秦克智) 已 register 到 index.json（含正确日期），但 `add_insurance_personnel()` 的 upsert 规则 `excluded.end_date >= insurance_personnel.end_date` 拒绝覆盖：旧 end=2026-12-08 (从 6894300 错填过来的) > 新 end=2026-09-16 → 跳过 UPDATE → 谭建芬仍是错日期。修复批次数据时需用 SQL `UPDATE WHERE id IN (...)` 直接绕开 upsert。

## 关键 Bug 修复要点（按时间倒序）
- **谭建芬 (id=220) end_date < start_date 反序 + 批单 policy_number 全错 + 减保跨保单误改 + SQL 参数顺序错位 bug（2026-09-16 4 bug 一并修复 ✅）**：用户反馈谭建芬 51303119711110358X start=2026-06-23 / end=2026-06-17（**反序 6 天**），要求排查同类 + 修复 + 防复发。
  - **Bug A 反序**：批单004（7116013100260072423004）"自2026年09月13日零时起生效"，该生效日应是减保谭建芬的 end_date，但 `personnel_extractor_node` 没把 `endorsement_effective_date` 传到 ExtractionResult → `_persist_policy_result` 拿不到 → 降级用 overall_start（主保单起期 2026-06-17）→ 谭建芬 end_date=2026-06-17 < start_date=2026-06-23。
  - **Bug B 批单 policy_number 全错为 81**：`_extract_policy_number` 对批单文件总是先匹配"保险单号" → 拿主保单号（81 开头）。63 条批单记录 policy_number 写成主保单号。重跑 27 份未入库批单 + 70 次 SQL 修正 63 条历史脏数据后 → 177 条批单记录 policy_number 正确。
  - **Bug C 减保跨保单误改**：徐成强 51011219850711091X 重跑四川众立批单0034742015 减保时 `deactivate_insurance(['51011219850711091X'])` 按 id_number 全表改，把华安一年保单(6100601045020260000875, 2026-06-16~2027-06-15) 改成失效 end_date=2026-05-22。修复：deactivate_insurance 新增 policy_number 参数，提供时 WHERE 增加 `policy_number = ?` 过滤；server.py `_persist_policy_result` 减保调用统一传 policy_number。
  - **Bug D deactivate_insurance SQL 参数顺序错位（隐性炸弹）**：函数 where_sql = "id_number IN (?,?,?) AND policy_number = ?" 但 params 顺序为 `[end_date, *params, *id_numbers]`（policy_number 拼到了 id_number 位置上）。SQLite 静默返回 rowcount=0 而不报错，所有带 policy_number 的减保调用实际**没有修改任何记录**。**这是隐藏最深的 bug**——Bug C 修复如果没发现 Bug D，依然无效。修复：参数顺序改为 `[end_date, *id_numbers, *params]`。
  - **同类问题排查**：全库扫描 `WHERE end_date < start_date` → 修复后 0 条；`policy_number LIKE '81%' AND source_file LIKE '%批单%'` → 修复后剩 12 条（10 条是万年县盛美 BD 主保单正确数据 + 2 条四川众立文件名截断历史遗留，无法靠文件名判断）。
  - **3 层修复 + 1 层兜底**：
    - L1 `extraction_result.py` 新增 `endorsement_effective_date` 字段
    - L2 `personnel_extractor_node` 从 `state.get("working_memory", {})` 读取 `endorsement_effective_date` 并写入 ExtractionResult
    - L3 `metadata_extractor._extract_policy_number` 对批单文件优先匹配"批单号"，并新增**文件名兜底**：若仍拿到 81 主保单号（PDF 无"批单号"标签，如 BD 格式），用 `parse_policy_filename` 从文件名提取（万年县盛美 BD 格式 `*_7116013100260112989001_BD.pdf` 等）
    - L4 `database.deactivate_insurance` 新增 policy_number 参数 + **修正 SQL 参数顺序**
  - **数据修复**：谭建芬 (220) → (2026-06-23, 2026-09-13, 失效, 7116013100260072423001)；徐成强 (1763) → 还原 (2026-06-16, 2027-06-15, 正常, 6100601045020260000875)；万年县盛美 BD 7 条 policy_number 修正（3008/3009→7116013100260112989001；3299-3303→7116013100260112989003）。备份：`data/app.db.bak.20260916_before_fix_endorsement_effective_date` + `data/app.db.bak.20260916_before_fix_wannianxian_policy_number`
  - **通用教训**：①字段传递链路要打通（endorsement_effective_date 在 metadata→personnel_extractor→server 之间全程透传）；②**SQL 参数顺序是隐性炸弹**——SQLite 静默成功 0 行，调试时必须用 `db.get_connection()` 手动连接复现+对照 rowcount，绝不能只看返回值；③测试函数时**绝不能用 `shutil.copy` 复制 DB 当测试库**——函数内 `get_connection()` 走 `DB_PATH`，仍指向生产库，本次测试把林世友 (823) 改成失效 + end_date=2025-01-01，立刻 SQL 还原
- **status 脏数据(增保) → 误判未参保 → 误发邮件/短信（2026-09-16）**：
- **status 脏数据(增保) → 误判未参保 → 误发邮件/短信（2026-09-16）**：段小平 (id=3988) status 被写成 '增保'，`get_active_insurance_by_id` 用 `status='正常'` 严格等值查询漏匹配 → 连续 3 天(9-14/15/16)向项目经理胡俊杰发"未参保"邮件+短信。全库 7 条同类脏数据（均来自 2c02 **华安财产保险**批单088 那次写入，pol=`6130101040320260000001-088`，投保人杭州班王重庆分公司）。三重根因：①写入层 4 处无 status 校验（`upsert/add_insurance_personnel`、`update_personnel`、`_parse_personnel_excel` 都 `p.get("status","正常")` 直接透传）；②检测层严格等值；③14 天/.def 通知链路直接消费 uninsured 无二次确认。三层防御修复：
  - L1 `database.py` 新增 `normalize_person_status(raw, end_date, today)`（别名 `_normalize_status`）+ `_MODIFICATION_TO_STATUS` 映射表；优先级=白名单原样→批改类型映射→未知值按 end_date 推断；**批改类型映射后必须再用 end_date 校正**（'增保'+已过期→失效，首版漏此步）
  - L2 `_parse_personnel_excel` 调用同一归一化
  - L3 `get_active_insurance_by_id` 改排除式 `(status IS NULL OR status='' OR status!='失效')`，未知 status 不再导致误报
  - 数据清洗 7 条→正常，备份 `data/app.db.bak.20260916_before_fix_status_whitelist`；修复后非法 status=0
  - **通用教训：凡入 DB 的枚举字段（status/policy_type/id_type）写入层必须白名单归一化**
- **deactivate_insurance 不更新 end_date bug（2026-09-15）**：秦克智 (id=1014) 等 10 条记录 status=失效 但 end_date=主保单止期（自相矛盾）。双重根因：① `deactivate_insurance()` 只更新 status 不动 end_date；② 批单 `endorsement_effective_date` 未单独提取，validator fallback 把 overall_start_date/overall_end_date 填成主保单起止日。修复：
  - `deactivate_insurance(id_numbers, end_date=None)` 新签名，提供 end_date 时同步 UPDATE end_date
  - `metadata_extractor_node` 新增正则 `_ENDORSEMENT_EFFECTIVE_PATTERN = r"自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*零时起\s*生效"` → `endorsement_effective_date`
  - `web_app/server.py _persist_policy_result` 减保时 `deactivate_end_date = endorsement_effective_date or overall_start`
  - 新增检测函数 `db.find_inconsistent_deactivations(today)` + API `GET /api/insurance/inconsistencies`
  - 数据已用 SQL 直 UPDATE 修复 10 条历史脏数据（含 299/300 孤儿数据补全 policy_number/source_file）；修复后 `status=失效 AND end_date>today` 全库扫描 = 0
  - 备份 `data/app.db.bak.20260915_before_fix_qinkezhi_status`
- **批单关联主保单 fallback + 3 层防御（2026-09-15）**：森炜 0072423000 批单001/002 上传时主保单未入库，fallback 误匹配 6894300 (同公司) 主保单 → 3 条记录 (谭建芬/袁发群/杨远成) 起止日期被错填 2026-06-09~2026-12-08（应 2026-09-16）。数据已用 SQL 直 UPDATE 修复，3 层防御代码提交 `90c96d1`：
  - L1 validator: `validator_node._link_to_main_policy` 加 `policy_number == policy_number` 相等校验（提交 `34105f8`）
  - L2 policy_library: 新增 `_policy_numbers_compatible()` 静态方法 + `find_main_policy()` 前缀兼容校验，利宝规则：批单 `71XX` ∩ 主保单 `81XX` 第 2 位相同 + 第 3-20 位相同
  - L3 上传入口: `_process_single_pdf()` 检测批单主保单缺失/不匹配 → return error「批单主保单缺失/不匹配」阻断入库
  - UI: `web_app/static/index.html` 加 `.date-warn` 琥珀色高亮 + ⚠ 图标 + 「仅日期异常」筛选按钮 + 页面异常计数徽章
- **大型保单跨页扩展 bug（>100 人，2026-09-14 下午）**：杭州班王保单 131 人只识 22 人；2c02 **华安财产保险**批单 088（杭州班王重庆，22 页 199 人）也只识 22。根因：续页判定强制要求表头词，但大型清单从第 2 页起常省略重复表头。修复：新增 `_is_list_continuation_page()` 用「≥3 个 18 位身份证」作续页强证据。备份 `data/app.db.bak.20260914_172800_before_large_policy_fix` + `data/app.db.bak.20260914_180500_before_2c02_batch_fix`。
  - **⚠️ 服务必须重启**：代码修复后 HTTP API 仍走旧代码（内存中 graph 对象）。验证方法：`python -c "graph.invoke(...)"` vs `curl /api/upload`。重启后 API 才生效。
  - **代码热更新端点（2026-09-14 19:00）**：`GET /api/agent/info` 看代码版本（git commit + 关键文件 mtime）；`POST /api/agent/reload` 用 `importlib.reload` 重载关键模块并重建 graph（无需重启服务）。完整模块列表在 `_GRAPH_CODE_FILES`（server.py line 81-91）。
- **table_extractor 起止日期误识（同一天，2026-09-14 上午）**：保单(2).pdf（利宝 上海鑫瓯 15 人）14 条 end_date 被填成 start_date。根因：post_region 跨入下一行，`dates[1]` 取到下一个人的"生效日期"。修复：截断到下一个身份证号之前。备份 `data/app.db.bak.20260914_165000_before_fix`。
- **众安"人员名单"清单页漏检（2026-09-11）**：`_LIST_MARKERS` 缺"人员名单"；扩展断的 `break` 过激 → 改为 3 步精确定位（标记命中+真实清单校验+跨页扩展跳过条款页）。HL1100001340910096.pdf 现 3 人全提取。
- **BD格式解析 + 批单 0001 日期补全（2026-09-09）**：filename_parser.py 加 BD 格式 + SQL 补全 2 条 NULL 记录。备份 `data/app.db.bak.20260909-092937`。
- **利宝批单日期缺失（2026-09-01）**：3 条万年县盛美批单记录用主保单期间 2026-08-27~2026-11-26 补全。备份 `data/app.db.bak.20260901-101442`。
- **中介公司误识投保人（2026-08-28）**：19 条被误识为"广东美保保险经纪"，DB 已按文件名修复 + `_INTERMEDIARY_KEYWORDS` 黑名单防御。

## ERP 同步打卡性能要点
- page_size 加大：fetch_all_punch_data=500、fetch_project_orders=500、fetch_user_list=1000
- executemany 比 SQLite 单条循环快 100x+
- 独立 ERP 接口必须并发：ThreadPoolExecutor(3) 拉三个接口 → max≈9s

## 短信/邮件双重 dedup
- 第一道：last_daily_check.punch_date（force=True 可绕过）
- 第二道：daily_sms_sent_today.phones（force 不可绕过，per-phone 维度）
- 状态 `.reminder_config.json`；scheduler 状态 `data/scheduler_state.json`

## ⚠️ 通知发送安全规则（用户明确要求）
- 任何邮件/短信发送操作前必须询问用户，得到明确允许后再发
- 包括：手动触发 `/api/summary/trigger?force=true` / `/api/reminder/check-expiry` / `/api/daily-check?force=true` / 修改 `notification_test_mode`
- 例外：scheduler 自动按时间触发的定时任务（用户已通过配置表达过同意）

## 服务稳定性
- 双击「一键启动服务.bat」启动；agent 启动的进程会被会话回收
- watchdog 崩溃自重启；重启不再每启动发邮件（last_run_date 持久化）
- bridge 与 server 生命周期联动（service_watchdog.py）：server 启→bridge 启；server 崩/退出→bridge 必杀；bridge 崩→自启。单实例锁 TCP 8767
- 本地常驻（双保险）：计划任务 `InsuranceAgentWatchdog`（SYSTEM 身份、开机自启）跑 `pythonw service_watchdog.py`；进程级崩溃+假死双检测
- 8765 **仅本机 `127.0.0.1` 监听**，无公网地址、无 Cloudflare Tunnel

## 数据表 生产/测试 切换（两种独立开关，勿混淆）
- 开关A（数据来源）：`punch_table_for_sms` → punch_records=生产 / punch_records_test=测试
- 开关B（通知路由）：`notification_test_mode` → 真实经理 vs 测试联系人
- 白名单：`punch_records` / `punch_records_test` / `punch_records_backup_*`，防 SQL 注入
- 切回：删 `punch_table_for_sms` 字段，重启服务即生效

## 保单人员去重
- 判重键 `(name, id_number)` + partial unique index `WHERE id_number != ''`
- upsert 保险型覆盖：仅新数据 `end_date >= 旧数据 end_date` 时 UPDATE；empty end_date 兜底

## MQ 桥接实时同步
- 入口 `insurance_agent/tools/mq_punch_bridge.py`（rocketmq backend，HTTP 协议，mq_http_sdk）
- 当前生产配置：topic=`JS_PROD_MQ`、group=`insurance-automation`（独立消费组）
- HTTP endpoint：`http://${INSTANCE_ID}.mqrest.cn-<region>-public.aliyuncs.com:80`（必须 `http://` 前缀 + `-public` 后缀）
- 错误分层速查：10060=TCP 被拦、SignatureDoesNotMatch=AK/SK、InvalidHost=host 不带 http://、AccessDenied=group 未建
- 项目在用户本机(C:\insurance-automation)，不受 WorkBuddy 沙箱网络限制
- 心跳 5 分钟 + RotatingFileHandler 10MB×5 → 月度单文件 30-40MB 稳定

## Windows .bat 脚本踩坑
- 用户系统 GBK 代码页：bat 写中文必须 ASCII（rem 注释除外）
- 检查换行用 Python 二进制：`open(p,'rb').read().count(b'\r\n')`，不要用 grep/git-bash
- UAC 自提权：管理 SYSTEM 进程必须 `net session >nul 2>&1` 失败则 `powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"`
- mshta vbscript 自提权不可靠：UAC 拒绝时一闪而关，沙箱无桌面永久挂起 → 让用户右键管理员运行
- 端口锁 PID 复用陷阱：`QueryFullProcessImageNameW` 验证 PID 指向 `\python.exe`/`\pythonw.exe`，否则视为死锁
- 重启 SYSTEM 服务用 ctypes：`OpenProcess(PROCESS_TERMINATE=0x0001) + TerminateProcess(h, 0)` 强杀，taskkill 大概率"拒绝访问"
- 鉴权用客户端 IP 别用 Host 头：`_client_ip(request)` 走 CF-Connecting-IP → X-Forwarded-For → socket 地址，本机+RFC1918 私有网段全放行