# 保险单识别项目核心记忆（精简版）

## 项目目标
从各种保险单 PDF 提取被保人员清单（姓名/证件号/所属公司/起始时间/起止时间/保险公司/批改类型[增保/减保]）。保单号字段需支持批单→主保单自动关联补全日期。

## 保险单格式速查（精简表）
| 保险公司 | 清单格式 | 逐人日期 | 用工单位 | 增减保 | 备注 |
|---|---|---|---|---|---|
| 利宝-保单 | table(序号/姓名/证件号/工种/用工单位) | ❌整体 | ✅列 | 纯增 | |
| 利宝-短期(1-3月) | table + 单"生效日期"列 | ❌整体(易触发 post_region 跨行 bug) | ✅列 | 纯增 | 修复:截断到下个身份证号前 |
| 利宝-批单(普通) | inline | ❌批单生效日 | ✅行内 | 纯增 | 无逐人日期→主保单期间补全 |
| 利宝-BD格式 | 公司名_保单号_BD.pdf | ✅批改日 | ✅ | 增/减 | filename_parser 正则 |
| 太保-明细表 | table(序号/姓名/证件号/岗位/起期/止期) | ✅ | ❌ | 纯增 | |
| 太保-人员清单 | table(无序号/无日期,用工=投保人) | ❌ | ❌ | 纯增 | |
| 华农-保单 | table(方案/姓名/证件号/职业/用工单位) | ❌ | ✅ | 纯增 | |
| 华农-批单 | inline(证件号:标签) | ✅批改日 | ✅ | 增/删 | |
| 中国人寿-在保名单 | **block_kv**(每人独立键值对) | ✅逐人 | ✅从「投保人」标签 | 纯增/批=增减替 | BlockKVExtractor(9-17 新增) |
| 中国人寿-变动清单 | table(双栏:增加+减少) | ✅ | ✅ | 增/减/替 | 「同期增减」减栏无 ID→无法去失效 |
| 国寿(其他) | table(序号/姓名/身份证号/职业类别) | ❌ | ❌ | 纯增 | |
| 人保关爱保个人 | individual(键值对) | ❌ | ❌ | 纯增 | |
| 黄河-批单 | table(变动清单) | ✅ | ✅ | 增/删 | |
| 黄河-扫描件雇主责任险 | table OCR(序号/姓名/身份证/职务/工种/**共同被保险人**/风险等级) | ❌ | ✅"共同被保险人" | 主纯增/批=增 | **全扫描件 OCR**(9-20 新增)。多公司混保单,"工种类"易被误填 company→`_looks_like_company_name` 兜底 |
| 华安-批单 | table(序号/方案/姓名/证件号/岗位/用工单位/职业等级/起止/批改时间) | ✅ | ✅ | 增/删 | 续保批改模式(P1 全部+P21-22 末尾页新增);用工单位跨行 |
| 平安-投保单 | no_list | — | — | — | 仅条款 |
| 安诚(ASHH) | table(投保人名称 空格分隔) | ❌ | 投保人 | 纯增 | ASHH=主,BSHH=批→均属太保(9-16 修正) |
| 众安在线-非灵工 | table(序号/姓名/证件号/职业代码/方案/实际用人单位/起止/保费) | ✅ | ✅ | 纯增 | 头词"人员名单"(非"人员清单");PyMuPDF 拆身份证成两行→`re.sub` 跨行拼接 |
| 众安灵工版 | no_list(不记名/总人数) | — | — | 总投 | |

## 关键识别规则
- **文件名含"投保单"≠投保申请书**:仅当同时无保单号且无清单页才判 `no_list`。例"逸趣投保单.pdf"实为保险单。
- **中介公司黑名单**:`广东美保保险经纪`/`保险经纪`/`代理公司`/`保险公估` → 跳到 `parse_policy_filename` 文件名提取。
- **BD 格式文件名**:`^(.+?)_(\d{16,30})_BD$`。
- **清单页定位(精确版)**:`_LIST_MARKERS` 命中 → `_is_real_list_page`(表头词+6位数字) → 排除 `_is_clause_page`(条款/附录);续页用 `_is_list_continuation_page`(≥3 个 18 位身份证)作强证据。
- **table_extractor post_region 截断**:截到下个身份证号前,否则 next-person 生效日期被误填为当前 end_date(同一天 bug)。
- **批单 inline 格式无逐人日期**:用主保单 start/end_date 兜底补全。

## 技术方案
- PDF 解析:PyMuPDF 文字层 + 扫描件 MiniMax-M3 视觉 OCR
- LangGraph:policy_parser → metadata_extractor → personnel_extractor → validator → output
- Extractors:table / inline / individual / **block_kv**(中国人寿在保名单) / ocr
- LLM:MiniMax-M3 (Anthropic协议,H-AGENT/.env)
- 服务:FastAPI (web_app/server.py :8765) + watchdog (service_watchdog.py) + 一键启动服务.bat

## 关键设计/模块
- **批单→主保单关联(L1+L2+L3)**:
  - L1 validator `_link_to_main_policy`:读 `working_memory["policy_type"]=="批单"` → 用 `main_policy_number` 精确查主保单表 → 不匹配时按 `_policy_numbers_compatible(批次号, 主保单号)` 前缀兼容(利宝批单 `71XX` 与主保单 `81XX` 第 2 位同 + 第 3-20 位同)
  - L2 `policy_library._policy_numbers_compatible` 兜底校验
  - L3 `_process_single_pdf` 上传时主保单缺失/不匹配直接 return error
- **保单库双表(`policy_library.py`)**:`PolicyRecord` 加 `main_policy_number` + `endorsement_effective_date`;`register()` 按 `policy_type` 分流入 `index_main.json` / `index_batch.json`;`find_main_policy_by_number` 精确匹配主表
- **`ExtractionResult` 字段透传**:新增 `batch_policy_number` / `main_policy_number` / `policy_type` 三个字段;`personnel_extractor_node` 从 `state.get("working_memory", {})` 读 → 写 ExtractionResult → server.py 收到
- **`_detect_endorsement(text, file_name)`**:文件名无"批单/BD"时,从 PDF 文本特征("批单号"+"保险单号"同存,或"本次批改"/"批文"/"批单生效日期")判定

## Bug 修复要点(按时间倒序,只留核心)
- **万年县盛美 4 条 NULL 期孤儿批单(9-18,commit b61d325)**:`find_main_policy_by_company` 第一个匹配错回旧保单;`_link_to_main_policy` `main_policy.policy_number != policy_number` 严格相等误判 71/81 不同→拒绝。修复:`find_main_policy_by_company_compatible(company, batch_policy_number)` 按兼容性迭代过滤;严格不等再用 `_policy_numbers_compatible` 二次放行。教训:严格相等不适合 71/81 设计差异(应兼容性前缀)
- **刘红才(1).pdf 缺日期优化(9-21)**:3-part 优化:① 保单库双表 + UI 双表 + 字段拆分+精确搜索;② 批单上传时自动查主保单补全日期(检测批单不只看文件名,也看文本特征);③ 刘红才入库时因 `upsert_insurance_personnel` 的 WHERE 子句 `end_date >= 旧 end_date` 在旧 end_date=NULL 时所有比较→NULL→rowcount=0 → 修复:包 `COALESCE(end_date, '1900-01-01')`。**3 层防御已经到位**:L1/L2/L3
- **中国人寿 block_kv + 变动清单双格式(9-17)**:`extractors/block_kv_extractor.py` 新建;table_extractor 加 pre_region 日期 + per-row mod_type(`同期增减/替换/置换`→增保);OCR prompt 加 `job_title`+`occupation_class`;`pymupdf_parser._detect_insurance_company` 改按命中次数加权(防"中国人寿财产"包含"中国人寿"重复计数) + 长关键词优先;品牌名 PDF 只写"国寿"→keywords 双轨。教训:① 跨行字段别用 `\S+`,必须 lookahead 捕获下个字段标签;② server.py `from ... import` reload 不更新→需 kill watchdog 重启 server
- **metadata_extractor logger NameError + BSHH 号段映射错(9-16)**:`BSHH` 实际是太保批单前缀,不是安诚。修复:补 `import logging` + 号段映射 ASHH→太保主/BSHH→太保批
- **段小平 insurance_company 误识"黄河"(9-16)**:`_COMPANY_PATTERNS` 缺"华安"+首次命中无加权+无号段映射。3 层修复:L1 加华安 pattern 顺序长关键词优先 / L2 按命中次数加权 / L3 `tools/company_extractor.detect_insurance_company_by_policy_number` 号段兜底(号段=承保机构发行的硬证据,最强)
- **谭建芬反序+批单号错+减保跨保单+SQL 参数错位(9-16,4 bug)**:①反序:批单生效日未透传→降级用主保单起期→end<start;②批单号全错 81:`_extract_policy_number` 总匹配"保险单号";③`deactivate_insurance(ids)` 按 id 全表改,跨保单误改;④**参数顺序错位隐性炸弹**:`where_sql` 含 `policy_number=?` 但 params 顺序 `[end_date, *params, *id_numbers]` 拼错位置,SQLite 静默返回 rowcount=0。修复:db 加 `policy_number` 参数 + 改 params 顺序为 `[end_date, *id_numbers, *params]`。教训:SQLite 静默成功 0 行调试必须用 `db.get_connection()` 复现 + 对照 rowcount
- **status 脏数据→误判未参保→误发邮件(9-16)**:段小平等 7 条 status='增保' → `status='正常'` 严格等值漏匹配 → 连续 3 天误发"未参保"邮件。3 层修复:L1 `db.normalize_person_status()` 白名单归一(白名单原样→批改类型映射→未知值按 end_date 推断);L2 `_parse_personnel_excel` 调用同样归一;L3 `get_active_insurance_by_id` 改排除式 `(status IS NULL OR status='' OR status!='失效')`
- **deactivate_insurance 不更新 end_date(9-15)**:`deactivate_insurance()` 只更新 status 不动 end_date;validator fallback 把 overall 填充为主保单起止日。修复:加 `end_date` 参数 + `_ENDORSEMENT_EFFECTIVE_PATTERN = r"自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*零时起\s*生效"`
- **大型保单跨页漏人(>100人,9-14)**:续页强制表头词,大型清单常省略。修复:`_is_list_continuation_page()` 用「≥3 个 18 位身份证」作强证据
- **table_extractor 起止同天(9-14)**:post_region 跨入下一个人,`dates[1]` 取到 next 人的生效日期。修复:截到下个身份证号前

## ERP / MQ / 短信 关键开关与陷阱
- **page_size 加大**:fetch_all_punch_data=500、fetch_project_orders=500、fetch_user_list=1000
- **MQ bridge**:topic=`JS_PROD_MQ`、group=`insurance-automation`;HTTP endpoint 必须 `http://${INSTANCE_ID}.mqrest.cn-<region>-public.aliyuncs.com:80`(`-public` 后缀必备);错误码 10060=TCP 拦、SignatureDoesNotMatch=AK/SK、InvalidHost=host 不带 http://、AccessDenied=group 未建
- **双 dedup**:`last_daily_check.punch_date`(force 可绕过)+ `daily_sms_sent_today.phones`(force 不可绕过,per-phone)
- **通知发送安全规则**:`/api/summary/trigger?force=true` / `/api/reminder/check-expiry` / `/api/daily-check?force=true` / 改 `notification_test_mode` 前必须问用户;唯一例外=scheduler 自动定时任务

## 服务稳定性
- 双击「一键启动服务.bat」启动;agent 启动的进程会被会话回收
- watchdog 崩溃自重启;重启不再每启动发邮件(last_run_date 持久化)
- bridge 与 server 生命周期联动
- 本地常驻:计划任务 `InsuranceAgentWatchdog`(SYSTEM 身份、开机自启)跑 `pythonw service_watchdog.py`
- 8765 **仅本机 127.0.0.1 监听**,无公网地址、无 Cloudflare Tunnel

## 数据表 生产/测试 切换(两种独立开关,勿混淆)
- 开关 A(数据来源):`punch_table_for_sms` → punch_records=生产 / punch_records_test=测试
- 开关 B(通知路由):`notification_test_mode` → 真实经理 vs 测试联系人
- 白名单:punch_records / punch_records_test / punch_records_backup_*,防 SQL 注入
- 切回:删 `punch_table_for_sms` 字段,重启服务即生效

## 保单人员去重 + upsert
- 判重键 `(name, id_number)` + partial unique index `WHERE id_number != ''`
- ⚠️ **upsert 保险型覆盖规则**:`ON CONFLICT ... DO UPDATE SET ... WHERE (insurance_personnel.end_date = '' OR excluded.end_date = '' OR excluded.end_date >= COALESCE(insurance_personnel.end_date, '1900-01-01'))`(9-21 修复 NULL 兼容);empty end_date 视为可被任何新值覆盖

## Windows .bat 脚本踩坑
- 用户系统 GBK 代码页:bat 写中文必须 ASCII(rem 注释除外)
- 检查换行用 Python 二进制:`open(p,'rb').read().count(b'\r\n')`,不要用 grep/git-bash
- UAC 自提权:`net session >nul 2>&1` 失败 → `powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"`
- mshta vbscript 自提权不可靠:UAC 拒绝一闪而关,沙箱无桌面永久挂起 → 让用户右键管理员运行
- 端口锁 PID 复用陷阱:`QueryFullProcessImageNameW` 验证 PID 指向 `\python.exe`/`\pythonw.exe`,否则视为死锁
- 重启 SYSTEM 服务用 ctypes:`OpenProcess(PROCESS_TERMINATE=0x0001) + TerminateProcess(h, 0)` 强杀,taskkill 大概率"拒绝访问"
- 鉴权用客户端 IP 别用 Host 头:`_client_ip(request)` 走 CF-Connecting-IP → X-Forwarded-For → socket 地址,本机+RFC1918 私有网段全放行

## 代码热重载 + 必重启边界
- 节点代码(nodes/*):`GET /api/agent/info` 看版本 → `POST /api/agent/reload` 用 importlib.reload 重载关键模块,无需重启
- ⚠️ **server.py 自身改动必须重启服务**(reload 不会 reload server.py);同理 utils/ 叶子层(pymupdf_parser/company_extractor/tools/filename_parser)需在 `_reload_graph_dependencies` 注册
- 杀进程用 `ctypes.windll.kernel32.TerminateProcess`(psutil.kill Windows 不可靠)
- 模块级 `from X import Y` reload 后仍指向旧 class object → 必须 kill watchdog 启动的 server → watchdog 自动重启
