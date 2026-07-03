# 保险单识别项目记忆

## 项目目标
从各种保险单PDF文件中提取被保人员清单（姓名、证件号码、所属公司、起始时间、起止时间）

## 关键发现 - 保险单格式差异
| 保险公司 | 人员清单格式 | 逐人日期 | 用工单位列 |
|----------|------------|----------|-----------|
| 利宝保险-保单 | 表格（序号/雇员姓名/证件号/性别/年龄/职业/用工单位） | ❌只有整体保险期限 | ✅有用工单位列 |
| 利宝保险-批单 | 行内（雇员姓名：XX，证件号：XX，用工单位：XX） | ❌只有批单生效日期 | ✅行内含用工单位 |
| 中国太平洋财产保险 | 表格（序号/姓名/证件号码/岗位名称/起期/止期） | ✅每人有起止时间 | ❌需从投保人信息获取 |

## 技术方案
- PDF解析: pymupdf 文字层提取 + 图片转换备选（扫描件用视觉模型OCR）
- 身份证验证: 6位区域码 + 4位年份(1940-2039) + 4位月日 + 3位序列 + 1位校验
- 格式学习: JSONFormatRegistry 自动学习并存储保险公司格式模式
- DI模式: Protocol/Adapter 分层，PyMuPDFParser 为适配器实现
- Agent 框架: LangGraph，StateGraph 编排 5 节点
- LLM 接入: 通过项目底座（H-AGENT 提供），不走自身 LLM

## 架构分层（DDD + DI）
```
domain/         纯领域模型（不依赖 infrastructure）
tools/          通用工具（任意 Agent 复用）
infrastructure/ 外部系统对接（PDF/格式注册表/LLM）
extractors/     提取策略（table/inline/ocr）
agents/         业务能力（按 capability 组织，含 states/nodes/tools）
```

## LangGraph 流程
START → policy_parser → metadata_extractor → personnel_extractor → validator → output → END

## 关键 Bug 修复
- PUA 字符: 0xF000-0xFFFF → 0xF800-0xFFFF + \uffff → ：映射
- Python 3.12+ `str.split()` 把 `：` 当空白 → 用正则 `[ \t\f\v]+` 替代
- 身份证正则: 年份 4 位、区域码 6 位（不是 2 位）
- `format_hint: "ocr"` 兜底逻辑要分清 scanned vs missing marker

## 已提交代码 (insurance-ai分支)
- insurance_agent/  (Phase 2 完整分层)
- 84 6c5aa  refactor(insurance_agent): 分层重构 + Agent 框架搭建 (Phase 2)
- 82f9c61  Phase 1: 保险单识别Agent核心模块 + H-AGENT框架基础

## 验证结果（4 真实 PDF）
| 文件 | 格式 | 人数 | 状态 |
|------|------|------|------|
| 批单_重庆选鹏 | inline | 2 | ✅ |
| 保单_重庆森炜 | table | 4 | ✅ |
| 保单_成都兴久隆 | table | 8 | ✅ |
| 南京大千保单 | 扫描件 | - | ⏸ Phase 3 |

## 待解决
- Phase 3: 接入 kimi-k2.6 视觉模型 OCR（已预留 `extractors/ocr_extractor.py`）
- git push 需用户配置 SSH host key（sandbox 阻止）
- LLMFactory 注入 kimi-k2.6 真实客户端（当前 factory 占位）
