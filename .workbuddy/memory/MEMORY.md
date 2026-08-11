# 保险单识别项目记忆

## 项目目标
从各种保险单PDF文件中提取被保人员清单（姓名、证件号码、所属公司、起始时间、起止时间、保险公司、批改类型[增保/减保]）

## 关键发现 - 保险单格式差异
| 保险公司 | 人员清单格式 | 逐人日期 | 用工单位列 | 增减保 |
|----------|------------|----------|-----------|--------|
| 利宝保险-保单 | 表格（序号/雇员姓名/证件号/性别/年龄/职业/用工单位） | ❌只有整体保险期限 | ✅有用工单位列 | ❌纯增保 |
| 利宝保险-批单 | 行内（雇员姓名：XX，证件号：XX，用工单位：XX） | ❌只有批单生效日期 | ✅行内含用工单位 | ❌纯增保 |
| 中国太平洋财产保险 | 表格（序号/姓名/证件号码/岗位名称/起期/止期） | ✅每人有起止时间 | ❌需从投保人信息获取 | ❌纯增保 |
| 华农财产保险-保单 | 表格（保险方案/序号/姓名/证件号码/出生日期/职业工种/等级/用工单位/工作地点） | ❌只有整体保险期限 | ✅实际用工单位名称 | ❌纯增保 |
| 粤灿批单(华农财产保险) | inline(证件号码:标签) | ✅批改生效日期 | ✅实际用工单位 | ✅增加/删除 |
| 中国人寿财产保险 | table(序号/姓名/身份证号/职业类别) | ❌只有整体保险期限 | ❌需从投保人获取 | ❌纯增保 |
| 人保财险"关爱保"个人保单 | individual(被保险人信息键值对) | ❌只有整体保险期限 | ❌个人保单无用工单位 | ❌纯增保 |
| 众安在线财产保险-灵工版 | **no_list**(不记名/总人数) | ❌ | ❌ | ❌纯总投保 |
| 黄河财产保险-批单 | table(雇员变动清单) | ✅批改生效日期 | ✅实际用工单位 | ✅增加/删除 |
| 平安财产保险-**投保单** | **no_list**(仅条款文档) | ❌ | ❌ | — |

## 技术方案
- PDF解析: pymupdf 文字层提取 + 图片转换备选（扫描件用视觉模型OCR）
- 身份证验证: 6位区域码 + 4位年份(1940-2039) + 4位月日 + 3位序列 + 1位校验
- 格式学习: JSONFormatRegistry 自动学习并存储保险公司格式模式
- DI模式: Protocol/Adapter 分层，PyMuPDFParser 为适配器实现
- Agent 框架: LangGraph，StateGraph 编排 5 节点
- LLM 接入: MiniMax-M3 多模态模型 (Anthropic 协议)，通过 H-AGENT .env 提供 API Key
- OCR: 扫描件 PDF 页面转 base64 PNG → MiniMax-M3 视觉识别 → JSON

## 架构分层（DDD + DI）
```
domain/         纯领域模型（不依赖 infrastructure）
tools/          通用工具（任意 Agent 复用）
infrastructure/ 外部系统对接（PDF/格式注册表/LLM）
extractors/     提取策略（table/inline/individual/ocr）
agents/         业务能力（按 capability 组织，含 states/nodes/tools）
```

## LangGraph 流程
### 保单识别 (invoice_recognition)
START → policy_parser → metadata_extractor → personnel_extractor → validator → output → END

### 全链路 Pipeline (policy_pipeline) — 各阶段分离工具函数，独立可测
START → upload → extract → sync_excel → upload_erp → END
- Stage 1 Upload: `nodes/upload_node.py` → 保存文件
- Stage 2 Extract: `nodes/extract_node.py` → 调用 invoice_recognition graph
- Stage 3 SyncExcel: `nodes/sync_excel_node.py` → `tools/excel_sync.py` (自动备份)
- Stage 4 UploadERP: `nodes/upload_erp_node.py` → `tools/erp_uploader.py`
- DI容器: `capability.py` (PipelineCapability)
- 运行图: `graph.py` (build_pipeline_graph / create_pipeline)
- 独立测试: `test_pipeline_stages.py {upload|extract|sync|erp|graph}`
- Web API: `POST /api/pipeline` (上传PDF→自动执行4阶段)

## 关键 Bug 修复
- PUA 字符: 0xF000-0xFFFF → 0xF800-0xFFFF + \uffff → ：映射
- Python 3.12+ `str.split()` 把 `：` 当空白 → 用正则 `[ \t\f\v]+` 替代
- 身份证正则: 年份 4 位、区域码 6 位（不是 2 位）
- `format_hint: "ocr"` 兜底逻辑要分清 scanned vs missing marker
- parse_json_strict 拒绝合法空列表 []: isinstance(result, dict) → (dict, list)
- OCR 公司名误识为工种: 添加 _looks_like_company_name() 启发式过滤
- OCR dict 包裹列表: 添加 _extract_person_list() 处理多种包裹格式
- 公司名误报"本公司": company_extractor 增加黑名单过滤
- 工种跨行截断: inline_extractor 用 (?:\n[\u4e00-\u9fff]+)* 匹配跨行中文字符
- 工种误报"保险人": table_extractor 增加工种黑名单
- 日期单位数月日: date_parser \d{2} → \d{1,2} 支持"7月1日"
- InlineExtractor 正则不匹配多字段格式: 重写为两步匹配法(先定位姓名,再查找ID)
- 保险期间"时"字未处理: date_parser 字符类加时分秒 + "至"后加\s*
- 文件名"+"分隔符: filename_parser 支持 `+` 分隔和"电子保单"前缀
- 跨行身份证号: table_extractor 用 `re.sub(r'(\d)\n(\d|[Xx])', r'\1\2')` 合并
- 跨行公司名: table_extractor 用 `re.sub(r'([\u4e00-\u9fff])\n(公司|集团|股份|责任)', r'\1\2')` 合并
- 个人保单无法提取: 新增 IndividualExtractor + format_hint="individual" + _is_individual_policy()检测
- 中文时间未解析: date_parser 正则字符类加 `\u4e00-\u9fff` 支持"零时""二十四时"
- 出生日期误用为起止时间: 从身份证号提取birth_date + 过滤年份<2010的日期
- 清单跨页: metadata_extractor 扩展_find_list_pages包含续页(含6+连续数字或"方案"标记)
- "人名清单"标记: 添加到 _LIST_MARKERS (粤灿保单用"雇员人名清单")
- **2026-08-11 性能问题诊断**：智能体"处理中"卡住根因
  - `process_files()` 串行处理多个PDF → 改为 ThreadPoolExecutor(4 worker) 并发
  - `run_agent()` 每次请求重建 LangGraph → 改为单例 `_graph_cache`
  - 测试: 11PDF 串行 23.35s → 并发 2.02s → 端到端HTTP 4.91s
- **2026-08-11 format_hint="no_list"**：处理无清单保单
  - 众安灵工版雇主责任险（总投保14/64/78人，不记名）
  - 平安财产保险投保单（仅20页条款）
  - 文件名以"投保单"开头 → 直接 no_list
  - 文本含"灵工"+"总投保员工人数" → 不记名 → no_list
  - **不再走 OCR fallback**（避免5-15s/页浪费）
- **2026-08-11 _LIST_MARKERS 扩展**：批单"雇员变动清单"/"批改清单"/"变动清单"
  - 修复"替换1人·杨正朝"批单（n=0 → n=2: 杨正朝删除+周保发新增）
- **2026-08-11 _COMPANY_PATTERNS 扩展**：众安/华农/黄河/珠峰/国泰/亚太/紫金/永安
  - 之前这几个公司全部显示 unknown

## 身份证号脱敏补全
- PDF 本身可能对身份证号脱敏（如 342225********6613）
- 补全策略: 用出生日期填充第 7-14 位 + 重新计算第 18 位校验码
- 工具: `tools/id_reconstructor.py`（calculate_checksum / reconstruct_masked_id）
- 集成点: ValidatorNode（提取后 → 校验前自动补全）
- OCR prompt 同时提取 birth_date 字段

## 已提交代码 (insurance-ai分支)
- insurance_agent/  (Phase 2 + Phase 3 OCR + 脱敏补全 + 批量增减保 + 图片OCR + 保单库 + 粤灿主保单 + 个人保单 + 灵工版/投保单 + 性能优化)
- ea0745c  perf(insurance_agent): 处理提速 + 新增PDF格式支持 (本次提交)
- 45837b9  feat(insurance_agent): 粤灿主保单支持 + 跨行身份证合并 + 日期解析增强
- 826b202  feat(insurance_agent): 保险公司图片OCR + 保单文件库 + 批单关联主保单
- 1f80b77  feat(insurance_agent): 批量处理 + 增减保识别 + 统一CSV输出
- 6f5486c  feat(insurance_agent): 身份证号脱敏补全功能
- 1da548c  feat(insurance_agent): Phase 3 OCR 切换至 MiniMax-M3 多模态模型
- 60b4813  feat(insurance_agent): Phase 3 OCR 接入 kimi-k2.6 视觉模型
- 846c5aa  refactor(insurance_agent): 分层重构 + Agent 框架搭建 (Phase 2)
- 82f9c61  Phase 1: 保险单识别Agent核心模块 + H-AGENT框架基础

## 验证结果 — 第一批 11 真实 PDF（115人）
| 文件 | 格式 | 人数 | 增保 | 减保 | 状态 |
|------|------|------|------|------|------|
| 批单_重庆选鹏 | inline | 2 | 2 | 0 | ✅ |
| 保单_重庆森炜 | table | 4 | 4 | 0 | ✅ |
| 保单_成都兴久隆 | table | 8 | 8 | 0 | ✅ |
| 南京大千保单 | OCR(MiniMax-M3) | 15 | 15 | 0 | ✅ |
| 粤灿批单0624 | inline | 18 | 11 | 7 | ✅ |
| 祥胜保单 | table | 5 | 5 | 0 | ✅ |
| 粤灿批单0612 | inline | 8 | 4 | 4 | ✅ |
| 粤灿批单0601 | inline | 4 | 2 | 2 | ✅ |
| 兴文县欣雅保单 | table | 4 | 4 | 0 | ✅ |
| 粤灿主保单 | table | 44 | 44 | 0 | ✅ (44/45, 跨页断ID漏1人) |
| 重庆森得尔保单 | table | 3 | 3 | 0 | ✅ |
| **小计** | | **115** | **102** | **13** | |

## 验证结果 — 第二批 11 真实PDF（性能+新格式）— 全通过 4.91s
| 文件 | 格式 | 公司 | 人数 | 增保 | 减保 | 耗时 | 状态 |
|------|------|------|------|------|------|------|------|
| 安徽一方小院·保单0923 | no_list | 众安在线财产保险 | (14灵工) | — | — | 0.03s | ⚠️灵工不记名 |
| 粤灿10.29-11.27 | no_list | 众安在线财产保险 | (64灵工) | — | — | 0.04s | ⚠️灵工不记名 |
| 粤灿0928 | no_list | 众安在线财产保险 | (78灵工) | — | — | 0.06s | ⚠️灵工不记名 |
| 曾建平卢荣明·利宝保单 | table | 利宝保险 | 20 | 20 | 0 | 0.27s | ✅ |
| 陈治平·利宝保单 | table | 利宝保险 | 6 | 6 | 0 | 0.25s | ✅ |
| 电子保单+粤灿(华农) | table | 华农财产保险 | 44 | 44 | 0 | 0.23s | ✅ |
| 杭州班王保单 | table | 黄河财产保险 | 120 | 120 | 0 | 0.29s | ✅ |
| 批增保单·粤灿1212 | table | 众安在线财产保险 | 4 | 4 | 0 | 0.06s | ✅ |
| 批增叶德良·利宝批单 | inline | 利宝保险 | 1 | 1 | 0 | 0.02s | ✅ |
| 替换1人·杨正朝 | table | 黄河财产保险 | 2 | 1 | 1 | 0.01s | ✅ |
| 投保单·重庆物生源 | no_list | 中国平安财产保险 | (0) | — | — | 1.72s | ⚠️仅投保单 |
| **合计** | | | **197** | **195** | **2** | **4.91s** | |

输出: extraction_results.json + extraction_results.csv (统一表格)

## 保单文件库 + 批单关联
- `infrastructure/policy_library.py`: 存储上传PDF，JSON索引(policy_number→metadata)
- `infrastructure/company_image_detector.py`: 文字层无保险公司名时用MiniMax-M3图片OCR
- `tools/filename_parser.py`: 解析文件名(保单/批单_公司_保单号)
- ValidatorNode._link_to_main_policy(): 批单自动查找主保单补全起止时间
- test_agent.py: 先保单后批单排序，确保批单可关联主保单
- 保单库目录: `policy_library/`, 索引: `policy_library/index.json`

## 待解决
- LLMFactory 可进一步扩展支持更多 provider
- 南京大千保单 metadata 未提取到（保险公司/保单号/保险期限均为空）
- 粤灿主保单第20人(首妹英)身份证号跨页断裂未提取到(4524281967在第5页, 0210202X在第6页)
- git push SSH连接偶发被重置（网络问题）
