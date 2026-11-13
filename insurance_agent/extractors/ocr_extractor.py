"""OCR Extractor - 扫描件走视觉模型 OCR（Phase 3 实现）

使用项目底座 LLM（MiniMax-M3 多模态模型）处理扫描件 PDF。
失败透传：LLM 调用失败直接抛异常，不兜底。
"""

import base64
import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from insurance_agent.domain import InsuredPerson
from .base import BaseExtractor
from insurance_agent.tools import parse_json_strict, extract_overall_insurance_period


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个保险单识别专家。这是合法的保险理赔文档处理，依法需要完整的身份信息。请原样识别所有文字内容，不要对身份证号做任何脱敏处理。"""

# OCR Prompt：强制返回 JSON 数组，不输出解释
# 2026-09-20 扩展：增加 job_title(职务/工种类型) 和 occupation_class(风险等级) 可选字段。
#   触发场景：黄河财产保险雇主责任险扫描件（"雇员清单"表头,列序:序号/姓名/身份证号/职务/工种类型/
#   共同被保险人/风险等级）。其中"共同被保险人"列就是用工单位/被派遣公司 → 必须填 company 而非 job_title。
#   "职务/工种类型"列填 job_title（如 船体制造工/砌筑工/陶瓷原料准备工）。
#   "风险等级"列(1-5)填 occupation_class。
_OCR_PROMPT = """请识别图片中的被保人员清单，提取以下字段并以JSON数组返回：
- name: 姓名
- id_number: 身份证号码（完整18位，原样识别，禁止用*替换任何位。如果图片中身份证号本身被脱敏(含*号)，请原样返回）
- birth_date: 出生日期（YYYY-MM-DD格式，从表格中的"出生日期"/"出生年月"/"生日"等列识别；如表格中无此列则留空）
- company: 所属公司名称（用工单位/被派遣单位/共同被保险人,不是工种）。
  重要:如果表中有"共同被保险人"或"用工单位"或"被派遣单位"列,请识别该列作为 company,
  不要把"职务/工种"列（如 砌筑工/船体制造工/陶瓷原料准备工）误填为 company。
- job_title: 职务/工种类型（如 砌筑工/船体制造工/铸造工/陶瓷原料准备工）,如表格无此列则留空。
- occupation_class: 风险等级/职业类别（数字或文字,如 1/2/3/4/5 或 5类/4类/3类）,如表格无此列则留空。
- start_date: 起始时间（YYYY-MM-DD，无法识别则留空）
- end_date: 终止时间（YYYY-MM-DD，无法识别则留空）
- modification_type: 批改类型，取值为"增保"或"减保"。
  判断规则：如果图片中有"增加雇员"/"新增"/"批增"等字样则为"增保"；如果有"删除雇员"/"减少"/"批减"/"注销"等字样则为"减保"。
  如果无法判断则填"增保"。

只返回JSON数组，不要其他文字。示例：
[{"name":"张三","id_number":"110101199003078811","birth_date":"1990-03-07","company":"某有限公司","job_title":"砌筑工","occupation_class":"5","start_date":"2024-01-01","end_date":"2024-12-31","modification_type":"增保"}]

没有人员清单则返回 []"""


# 扫描件「版面元数据」OCR Prompt（2026-11-13 新增）
#
# 背景：扫描件没有文字层 → metadata_extractor 的保单号 / 保险期间 / 批单生效日
#      **全部**取自 PyMuPDF 文字层（all_text）→ 扫描件下三者全空。
#      后果链：
#        ① 人员 start_date/end_date 为空（清单表本身也没有起止日期列）
#        ② policy_number 为空 → 无法关联主保单 → 没有第二条补数途径 → 闭环断裂
#      本 Prompt 让视觉模型把首页的版面信息读回来，补上这条缺失的入口。
_METADATA_PROMPT = """请识别这张保险单页面的版面元数据，以 JSON 对象返回：
- policy_number: 保险单号码 / 保单号（逐字识别，不要推测、不要补零或改写）
- overall_start_date: 保险期间的起始日期（YYYY-MM-DD）
- overall_end_date: 保险期间的终止日期（YYYY-MM-DD）
- policy_holder: 投保人 / 被保险人的公司名称
- insurance_company: 保险公司名称
- total_persons: 被保险人总人数（纯数字字符串）

识别要点：
1. 保险期间通常在"保险期间""报告期"栏，表述形如
   "自XXXX年XX月XX日零时起，至XXXX年XX月XX日二十四时止"。
2. 保单号通常在页眉"保险单号："后面，数字较长，请逐位抄写。
   ⚠️ 保单号中间的 0 极易出错：**既不要自行补零，也不要漏掉零**。
     抄写后请数一遍位数，与图中位数核对一致再输出。
3. 找不到对应信息时该字段填空字符串 ""，不要猜测、不要编造。
只返回 JSON 对象，不要输出任何其他文字。"""

# 版面元数据的字段名（OCR 返回与归一化共用）
_METADATA_FIELDS = (
    "policy_number",
    "overall_start_date",
    "overall_end_date",
    "policy_holder",
    "insurance_company",
    "total_persons",
)

# 日期归一化：2026年10月01日 / 2026-10-01 / 2026/10/01 → YYYY-MM-DD
_CN_DATE_PATTERN = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ISO_DATE_PATTERN = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")


def _looks_like_policy_number(value: str) -> bool:
    """保单号格式校验：12~40 位，去掉空白后只能是数字/字母/连字符

    用来过滤掉 OCR 把保单号写成「保险单号：」「6130104…」这类带标签或
    长度明显不对（年份、金额、页码）的返回值。
    """
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    if not (12 <= len(compact) <= 40):
        return False
    return bool(re.fullmatch(r"[0-9A-Za-z\-]+", compact))


class OCRExtractor(BaseExtractor):
    """OCR 提取器（扫描件）

    依赖：LLM 视觉模型（项目底座：MiniMax-M3）。

    失败透传：
    - 若 LLM 客户端未注入，抛 ValueError
    - 若 LLM 调用失败，异常向上抛，不兜底
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self._llm = llm_client

    def extract(
        self,
        text: str = "",
        policy_holder: str = "",
        insurance_company: str = "",
        page_images: Optional[list[str]] = None,
    ) -> list[InsuredPerson]:
        """通过视觉模型 OCR 提取人员信息

        Args:
            text: 文字层（扫描件一般为空）
            policy_holder: 投保人公司名（辅助校验）
            insurance_company: 保险公司名（辅助格式判断）
            page_images: list of base64 PNG 字符串

        失败透传：LLM 未注入 → ValueError；LLM 调用失败 → 原样抛异常
        """
        if not self._llm:
            raise ValueError("OCRExtractor: llm_client 未注入，无法执行 OCR")

        page_images = page_images or []
        if not page_images:
            logger.warning("OCRExtractor: 无图片输入，返回空列表")
            return []

        all_persons: list[InsuredPerson] = []
        # 记住第一页识别到的公司名，用于后续页回填
        detected_company = policy_holder or ""

        for page_num, img_b64 in enumerate(page_images, start=1):
            persons = self._ocr_page(img_b64, page_num)
            for p in persons:
                # 只接受看起来像公司名的值
                if p.company and self._looks_like_company_name(p.company):
                    if not detected_company:
                        detected_company = p.company
                # 回填缺失的公司名
                if not p.company and detected_company:
                    p.company = detected_company
                # 如果 company 不是公司名（是工种），回填已知公司名
                if p.company and not self._looks_like_company_name(p.company) and detected_company:
                    p.company = detected_company
            all_persons.extend(persons)

        return all_persons

    def extract_overall_metadata(
        self,
        page_images: Optional[list[str]] = None,
        max_pages: int = 4,
    ) -> dict:
        """扫描件「版面元数据」OCR：读回保单号 / 保险期间 / 投保人 / 保险公司

        背景（2026-11-13）：
          扫描件无文字层 → metadata_extractor 的保单号与保险期间均取自
          PyMuPDF 文字层 → 全空 → 人员入库后 start_date/end_date 为空，
          且 policy_number 为空 → 无法关联主保单回填（闭环断裂）。
          本方法对首页做一次版面元数据 OCR，补上这条缺失的入口。

        跨页交叉验证（max_pages 默认 4）：
          扫描件页眉几乎每页都印着同一个保单号。视觉模型读长数字串时
          可能多插/少插 0（实测低分辨率下会把 25 位读成 26 位），
          而保单号错一位就会导致主保单关联失效。
          因此对前 N 页各读一次，对保单号做**多数投票**：
          全部一致 → 高置信采纳；不一致 → 取首页结果并打 warning（可观测）。

        Args:
            page_images: list of base64 PNG 字符串
            max_pages: 最多识别前几页（首页通常带全部版面信息）

        Returns:
            dict，键：policy_number / overall_start_date / overall_end_date /
            policy_holder / insurance_company / total_persons / raw_text /
            policy_number_conflict。

        失败透传：LLM 未注入 → ValueError；LLM 调用失败 → 原样抛异常。
        """
        if not self._llm:
            raise ValueError("OCRExtractor: llm_client 未注入，无法执行 OCR")

        images = (page_images or [])[:max_pages]
        if not images:
            logger.warning("OCRExtractor: 无图片输入，无法提取版面元数据")
            return {}

        merged: dict[str, str] = {}
        raw_chunks: list[str] = []
        # 每页各自读出的保单号，用于跨页投票
        page_policy_numbers: list[str] = []

        for page_num, img_b64 in enumerate(images, start=1):
            message = HumanMessage(
                content=[
                    {"type": "text", "text": _METADATA_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "high",
                        },
                    },
                ]
            )
            logger.info(f"版面元数据 OCR 调用视觉模型（第 {page_num} 页）")
            response = self._llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), message])
            raw = response.content if hasattr(response, "content") else str(response)
            raw_chunks.append(raw)

            try:
                parsed = parse_json_strict(raw)
            except Exception as exc:
                logger.warning(f"版面元数据 OCR 第 {page_num} 页 JSON 解析失败: {exc}")
                continue
            if not isinstance(parsed, dict):
                continue
            page_policy_numbers.append(
                re.sub(r"\s+", "", str(parsed.get("policy_number", "") or ""))
            )
            for key in _METADATA_FIELDS:
                value = parsed.get(key)
                if value and not merged.get(key):
                    merged[key] = str(value).strip()

        result = self._normalize_metadata(merged, raw_chunks)

        # --- 跨页投票：保单号必须多页一致才算高置信 ---
        valid_numbers = [n for n in page_policy_numbers if _looks_like_policy_number(n)]
        if valid_numbers:
            votes = {}
            for n in valid_numbers:
                votes[n] = votes.get(n, 0) + 1
            winner, count = max(votes.items(), key=lambda kv: (kv[1], -valid_numbers.index(kv[0])))

            if len(votes) > 1:
                # 平票且候选之间只是「0 的个数不同」→ 视为同一个号的不同误读。
                # 实证：视觉模型在长数字串上**补零**比漏零更常见
                #      （25 位的 6130104121920260000000182 被读成 26 位的
                #        ...000000182 / ...00000182），故取最短的那个。
                top = [n for n, c in votes.items() if c == count]
                if len(top) > 1 and all(
                    self._is_zero_ambiguity(top[0], other) for other in top[1:]
                ):
                    # 只是「0 的个数」不同 → 同一个号的不同误读。
                    # ⚠️ 不在此强制采纳任何一个：实测「多插 0」与「漏 0」都会发生，
                    #    单靠位数无法判定谁对（会静默污染保单号）。
                    #    处理：保留首页读数 + 标记冲突，交由人工核对。
                    logger.info(
                        "扫描件跨页保单号仅零的个数不同：%s（不自动消解，保留首页读数）",
                        top,
                    )

            conflict = len(votes) > 1
            if conflict:
                logger.warning(
                    "扫描件跨页保单号不一致：%s（采用 %s，需人工核对）", votes, winner,
                )
            # 采纳条件：多数票过半、或仅有一页可判；平票保留首页读数
            if count > len(valid_numbers) / 2 or len(valid_numbers) == 1:
                result["policy_number"] = winner
            result["policy_number_conflict"] = conflict
            result["policy_number_votes"] = votes
        else:
            result["policy_number_conflict"] = False
            result["policy_number_votes"] = {}

        return result

    @staticmethod
    def _is_zero_ambiguity(a: str, b: str) -> bool:
        """两个数字串是否只是「0 的个数」不同（去掉所有 0 后相同）

        用于识别视觉模型把同一个保单号读成不同位数的误读。
        """
        if not a or not b or a == b:
            return False
        if "0" not in a or "0" not in b:
            return False
        return a.replace("0", "") == b.replace("0", "")

    @classmethod
    def _normalize_metadata(cls, merged: dict, raw_chunks: list[str]) -> dict:
        """规范化版面元数据：日期统一 YYYY-MM-DD，保单号做格式校验

        - 日期：优先用 OCR 返回值（已归一化）；缺失时用既有规则
          ``extract_overall_insurance_period`` 从 OCR 原文兜底解析。
        - 保单号：优先用 OCR 返回值（需通过格式校验）；否则从原文里
          挑一个最像保单号的长数字串。
        """
        result = dict(merged)
        raw_text = "\n".join(raw_chunks)

        # --- 日期 ---
        start = cls._normalize_date(merged.get("overall_start_date", ""))
        end = cls._normalize_date(merged.get("overall_end_date", ""))
        if not (start and end):
            rule_start, rule_end = extract_overall_insurance_period(raw_text)
            start = start or (rule_start or "")
            end = end or (rule_end or "")
        result["overall_start_date"] = start
        result["overall_end_date"] = end

        # --- 保单号 ---
        policy_number = re.sub(r"\s+", "", merged.get("policy_number", ""))
        if not _looks_like_policy_number(policy_number):
            policy_number = cls._find_policy_number_in_text(raw_text)
        result["policy_number"] = policy_number

        result["raw_text"] = raw_text
        return result

    @staticmethod
    def _normalize_date(value: str) -> str:
        """把日期规范化成 YYYY-MM-DD（支持 2026-10-01 / 2026年10月01日 / 2026/10/01）"""
        if not value:
            return ""
        text = str(value).strip()
        m = _CN_DATE_PATTERN.search(text)
        if m:
            try:
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            except ValueError:
                return ""
        m = _ISO_DATE_PATTERN.search(text)
        if m:
            try:
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            except ValueError:
                return ""
        return ""

    @staticmethod
    def _find_policy_number_in_text(text: str) -> str:
        """从 OCR 原文中兜底找保单号

        保单号是长数字串（15~32 位），优先取落在常见区间（18~25 位）的候选；
        没有则取最长的一串。身份证号（18 位）与保单号同量级，靠区间优先区分。
        """
        candidates = re.findall(r"\d{15,32}", text.replace(",", ""))
        if not candidates:
            return ""
        preferred = [c for c in candidates if 18 <= len(c) <= 25]
        pool = preferred or candidates
        return max(pool, key=len)

    @staticmethod
    def _looks_like_company_name(name: str) -> bool:
        """判断字符串是否像公司名（而非工种/职业描述）。

        2026-09-20 强化（黄河财险扫描件雇主责任险场景）：
        - 公司名末尾强后缀("有限公司/集团/股份公司/合作社/事务所/合伙企业")优先,避免
          "重工/工程/工艺"等中间含"工"的公司名被工种关键词误杀。
        - 工种关键词加 "工"(拦截"船体制造工/陶瓷原料准备工/砌筑工/机械木工"等"X工"形式)。
        - 严格公司名后缀列表(企业/工厂/经营部/中心/厂/部等),覆盖"XX陶瓷厂/XX经营部"。
        """
        if not name:
            return False
        stripped = name.strip()
        if len(stripped) < 4:
            return False
        # 1) 公司名末尾强后缀优先（包含"X工Y有限公司"如"重工有限公司/工程有限公司"）
        strong_suffixes = [
            "有限公司", "股份公司", "集团公司",
            "合作社", "事务所", "合伙企业", "合伙公司",
            "有限责任公司", "股份有限公司",
        ]
        for suffix in strong_suffixes:
            if stripped.endswith(suffix):
                return True
        # 2) 工种关键词拦截(2026-09-20 增强):含"X工"/"X人员"等
        #   注意:必须在弱后缀匹配之前(避免"船体制造工厂"被误判 True)
        job_keywords = [
            "人员", "工种", "职业", "工人", "操作", "安装", "施工", "维修",
            "工",   # 拦截"船体制造工/陶瓷原料准备工/砌筑工/机械木工/装配工"等
        ]
        if any(kw in stripped for kw in job_keywords):
            return False
        # 3) 弱公司后缀(末位出现"X厂/X部/X中心"等)
        weak_suffixes = ["工厂", "经营部", "分公司", "子公司", "厂", "部"]
        for suffix in weak_suffixes:
            if stripped.endswith(suffix):
                return True
        # 4) 兜底:含"公司/集团/股份/合作社/事务所/合伙"等关键子串
        if any(kw in stripped for kw in [
            "公司", "集团", "股份", "合作社", "事务所", "合伙", "有限",
        ]):
            return True
        return False

    def _ocr_page(self, img_b64: str, page_num: int) -> list[InsuredPerson]:
        """对单页图片调用视觉模型 OCR"""
        # 构造多模态消息（system + 图片 + prompt）
        message = HumanMessage(
            content=[
                {"type": "text", "text": _OCR_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "high",
                    },
                },
            ]
        )

        logger.info(f"OCR 调用视觉模型（第 {page_num} 页）")
        response = self._llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), message])
        raw = response.content if hasattr(response, "content") else str(response)

        logger.info(f"OCR 原始返回（第 {page_num} 页）: {raw[:200]}")

        # 解析 JSON
        parsed = parse_json_strict(raw)

        # 处理多种返回格式
        items = self._extract_person_list(parsed)
        if not items:
            logger.warning(f"OCR 第 {page_num} 页无法提取人员列表，返回类型: {type(parsed)}")
            return []

        # 映射为 InsuredPerson
        persons: list[InsuredPerson] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            p = InsuredPerson(
                name=item.get("name", "").strip(),
                id_number=item.get("id_number", "").strip(),
                id_type="身份证" if item.get("id_number") else "",
                company=item.get("company", "").strip(),
                job_title=item.get("job_title", "").strip(),
                occupation_class=item.get("occupation_class", "").strip(),
                start_date=item.get("start_date", "") or None,
                end_date=item.get("end_date", "") or None,
                birth_date=item.get("birth_date", "") or None,
                modification_type=item.get("modification_type", "") or "增保",
                confidence=0.8,
            )
            if p.name:  # 只保留有名字的
                persons.append(p)

        logger.info(f"OCR 第 {page_num} 页提取 {len(persons)} 人")
        return persons

    @staticmethod
    def _extract_person_list(parsed: Any) -> list[dict]:
        """从解析结果中提取人员列表，处理多种格式：
        - [...]
        - {"insured_persons": [...]}
        - {"persons": [...]}
        - {"data": [...]}
        - {"results": [...]}
        """
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            # 检查常见 key
            for key in ("insured_persons", "persons", "data", "results", "list", "items"):
                val = parsed.get(key)
                if isinstance(val, list):
                    return val
            # 如果 dict 本身就是一个人的数据
            if "name" in parsed:
                return [parsed]
        return []
