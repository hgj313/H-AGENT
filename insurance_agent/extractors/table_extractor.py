"""Table Extractor - 表格格式人员清单

适用格式（如太平洋保险雇员清单、中国人寿保单）：
    序号 | 姓名 | 证件类型 | 证件号码 | 岗位名称 | 起期 | 止期
    1    | 李刚 | 身份证  | 512528197612124918 | 钢结构安装工 | 2026-06-24 | 2026-09-24

也支持被保险人名单格式：
    序号 | 姓名 | 身份证号 | 职业类别 | 承保方案
    1    | 黄嗣彬 | 450802198506193118 | ... | 01

支持批改类型检测：
- 文本中出现"增加"/"批增" → 增保
- 文本中出现"删除"/"减少"/"批减" → 减保
- 默认 → 增保
"""

import re
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import (
    extract_chinese_id_from_text,
    extract_names_near,
    extract_dates_near,
    extract_company_name,
)
from .base import BaseExtractor


class TableExtractor(BaseExtractor):
    """表格格式提取器

    策略：先用身份证号定位"人"的位置，再从上下文提取姓名/日期/公司/工种
    自动检测增保/减保标记。
    """

    # 常见工种模式（用于在上下文里捕获岗位名称）
    # 最低 1 个前缀字 + 工/员/师/者/人 后缀，以兼容 2 字工种（石工/焊工/漆工）
    _JOB_PATTERN = re.compile(
        r"([\u4e00-\u9fff]{1,9}(?:工|员|师|者|人))"
    )

    # 工种误报黑名单（不是工种的词）
    _JOB_BLACKLIST = {
        "保险人", "投保人", "被保险人", "受益人", "经办人", "负责人",
        "联系人", "代理人", "证人", "签章人", "业务员",
        # 通用高频词，容易误匹配为工种
        "员工", "人员", "工人", "雇员", "商户", "商人", "客人", "主人",
        "个人", "他人", "前人", "后人", "旁人", "行人", "动人", "熟人",
    }

    # 减保标记
    _REMOVE_MARKERS = ["删除", "减少", "批减", "减保", "注销"]
    # 增保标记
    _ADD_MARKERS = ["增加", "新增", "批增", "增保"]
    # 替换标记（2026-09-17 新增）：中国人寿"被保险人变动清单"含「替换」列
    _REPLACE_MARKERS = ["替换", "置换"]
    # 同期替换/增减标记（2026-09-17 增补）：7月31替换人 变动类型列值为"同期增减"
    # 表示"新+旧同步替换"——这种格式的PDF「减少被保险人」列只显示姓名+编号
    # 没有身份证号，extractor 只能抓到「增加」一侧；mod_type 一律标 增保
    _SIMULTANEOUS_MARKERS = ["同期增减", "同期替换", "同期置换"]

    # 变动清单格式表头（中国人寿"被保险人变动清单"批单专用，2026-09-17 新增）
    # 用于在 ID 之前定位每人的"变动类型"+"被保险人类型"+"姓名"+"个人编号"+"生效日"+"终止日"
    # 这些字段全部在 ID 之前（与利宝保单相反），不能仅搜 post_region
    _PRE_ID_LOOKBACK = 200  # 在 ID 之前搜索多少字符找 变动类型/姓名/日期

    # 工种误报词（除 _JOB_BLACKLIST 外，被保险人变动清单特有的"组合词"）
    # 例："增加主被保险人" / "减少连带被保险人" — 都不是工种
    # 2026-09-17 增补：预处理的行序列 `1生效增加主被保险人` 中"生效增加"也会被 _JOB_PATTERN
    # 贪婪匹配 → "生效增加主被保险人"；加这个到噪声表。
    _VARIATION_NOISE = {
        "增加", "减少", "删除", "替换", "置换", "批增", "批减",
        "主被保险人", "连带被保险人", "附属被保险人", "被保险人",
        "增加主被保险人", "减少主被保险人", "替换主被保险人",
        "增加连带被保险人", "减少连带被保险人", "替换连带被保险人",
        "生效增加主被保险人", "生效减少主被保险人", "生效替换主被保险人",
        "不生效增加主被保险人", "不生效减少主被保险人", "不生效替换主被保险人",
        "生效", "不生效",
    }

    # 表格表头列名（2026-09-17 新增）
    # 中国人寿"被保险人变动清单"的列名会被 PyMuPDF 拼成一行（"序号是否生效变动类型被保险人类型..."），
    # 然后被 _JOB_PATTERN 误匹配成"被保险人类型"。这些词都不能作为 job_title 出现。
    _TABLE_HEADER_KEYWORDS = (
        "序号", "是否生效", "变动类型", "被保险人类型", "姓名", "个人编号",
        "生效日", "终止日", "组号", "组名", "证件类型", "证件号码",
        "险种", "保额", "标准保费", "应收", "应付",
        "受理人员", "受理日期", "业务专用章",
    )

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        persons = []
        if not text:
            return persons

        # 检测批改类型
        mod_type = self._detect_modification_type(text)

        # 只在 "人员清单" 标记之后搜索
        list_markers = ["人员清单", "雇员清单", "雇员人名清单", "人名清单", "被保险人清单", "员工清单", "被保险人名单"]
        list_text = text
        for marker in list_markers:
            idx = text.find(marker)
            if idx >= 0:
                list_text = text[idx:]
                break

        # 预处理：合并 PDF 表格中跨行断开的内容
        # 1. 合并跨行身份证号: "4527251967\n0226048X" → "45272519670226048X"
        #    注意：前段要求≥3位数字，避免误伤日期时间文本
        #    （如"2026-04-03 00:00:00\n2026-09-10"里"00\n2"是时分秒，不应合并）
        list_text = re.sub(r'(\d{3,})\n(\d|[Xx])', r'\1\2', list_text)
        # 2. 合并跨行公司名: "广州市粤灿建设工程有限\n公司" → "广州市粤灿建设工程有限公司"
        list_text = re.sub(r'([\u4e00-\u9fff])\n(公司|集团|股份|责任)', r'\1\2', list_text)
        # 3. 去除"制单时间"页脚噪声（含日期，会干扰每人起止日期提取）
        #    例: "制单时间：2026年03月23日15时16分12秒"
        #    2026-09-17 增补：中国人寿"被保险人变动清单"含"受理日期/受理时间"标签
        #    同样会干扰人员起止日期提取（"受理时间：2026年07月31日"会被误当作
        #    该行人员的生效日）。"受理时间"是这份业务受理的日期，不是人员生效日。
        list_text = re.sub(r'制单时间[：:]\s*\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[^\n]*', '', list_text)
        list_text = re.sub(r'受理日期[：:]\s*\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[^\n]*', '', list_text)
        list_text = re.sub(r'受理时间[：:]\s*\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[^\n]*', '', list_text)
        list_text = re.sub(r'出具日期[：:]\s*\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[^\n]*', '', list_text)
        # 4. 合并跨行工种（表格单元格内换行）:
        #    例: "起重装卸机械\n操作工（吊车\n）" → "起重装卸机械操作工（吊车）"
        #    4a. 先合并括号跨行 "吊车\n）" → "吊车）"
        list_text = re.sub(r'([\u4e00-\u9fff（])\n(）)', r'\1\2', list_text)
        #    4b. 再合并工种主体跨行 "机械\n操作工" → "机械操作工"
        #        （后一行须以工/员/师/者/人结尾，且排除"雇员/员工/人员"等表头词，避免误合并表头）
        #        注意：前一行结尾不能是 雇佣性质 取值（是/否/有/无），否则会把
        #        "是\n石工" 误合并成 "是石工"。工种永远在第1列、雇佣性质在第末列，二者不会相邻。
        list_text = re.sub(
            r'((?!是|否|有|无)[\u4e00-\u9fff（])\n((?!雇员|员工|人员)[\u4e00-\u9fff]{1,8}(?:工|员|师|者|人))',
            r'\1\2',
            list_text,
        )

        # 1. 定位所有合法身份证号
        valid_ids = extract_chinese_id_from_text(list_text)
        if not valid_ids:
            return persons

        # 2. 找到每个身份证号在 list_text 中的位置
        for id_number in valid_ids:
            id_pos = list_text.find(id_number)
            if id_pos < 0:
                continue

            # 3. 在身份证号附近提取姓名
            name_candidates = extract_names_near(list_text, id_pos, window=200)
            name = name_candidates[-1] if name_candidates else ""

            # 3.5 从身份证号中提取出生日期（第7-14位 YYYYMMDD）
            birth_date = ""
            if len(id_number) >= 14:
                birth_year = id_number[6:10]
                birth_month = id_number[10:12]
                birth_day = id_number[12:14]
                birth_date = f"{birth_year}-{birth_month}-{birth_day}"

            # 身份证号之后的文本（表格中起止日期/工种/公司都在证件号之后）
            raw_post_region = list_text[id_pos:id_pos + 400]

            # 关键修复（2026-09-14）：截断 post_region 到下一个身份证号之前
            # 否则会把"下一个人员的生效日期"误当作"当前人员的起止日期"，
            # 当所有人员的生效日期都相同时（利宝保单常见格式），
            # 会导致 end_date 被错误地填成 start_date（即"起始/起止日期都是同一天"）。
            next_id_pos = len(raw_post_region)
            for other_id in valid_ids:
                if other_id == id_number:
                    continue
                pos = raw_post_region.find(other_id, 18)  # 跳过当前ID自身
                if 0 < pos < next_id_pos:
                    next_id_pos = pos
            post_region = raw_post_region[:next_id_pos]

            # 身份证号之前的文本（2026-09-17 新增）
            # 中国人寿"被保险人变动清单"格式：姓名/生效日/终止日/变动类型 都在 ID 之前
            # 截断到上一个身份证号之后（避免混入前一人数据）
            prev_id_boundary = max(0, id_pos - self._PRE_ID_LOOKBACK)
            for other_id in valid_ids:
                if other_id == id_number:
                    continue
                pos = list_text.rfind(other_id, 0, id_pos)
                if pos > 0:
                    boundary = pos + 18  # 跳过 ID 自身（18位）
                    if boundary > prev_id_boundary:
                        prev_id_boundary = boundary
            pre_region = list_text[prev_id_boundary:id_pos]

            # 4. 在身份证号前后提取日期
            #    2026-09-17 增补：中国人寿"被保险人变动清单"格式起止日期在 ID 之前
            #    优先级：post_region 优先（标准 table），pre_region 兜底
            dates_post = [
                d for d in extract_dates_near(post_region, 0, window=400)
                if d != birth_date and int(d[:4]) >= 2010
            ]
            dates_pre = [
                d for d in extract_dates_near(pre_region, 0, window=400)
                if d != birth_date and int(d[:4]) >= 2010
            ]
            if dates_post:
                dates = dates_post
            else:
                dates = dates_pre
            start_date = dates[0] if len(dates) >= 1 else ""
            end_date = dates[1] if len(dates) >= 2 else ""
            # 兜底：起始时间晚于起止时间（识别反了）时交换
            if start_date and end_date and start_date > end_date:
                start_date, end_date = end_date, start_date

            # 4.5 (2026-09-17 新增) 每行 mod_type 检测
            # 中国人寿"被保险人变动清单"在 pre_region 含变动类型列（增加/减少/替换），
            # 同一份批单可能混合增/减（7月31替换人 (1).pdf 验证过）→ 必须 per-row 检测
            row_mod_type = self._detect_row_modification_type(pre_region + post_region)
            mod_type_for_person = row_mod_type if row_mod_type else mod_type

            # 5. 在身份证号附近提取公司名 / 用工单位
            company = ""
            # 优先用工单位标签（post_region）
            m_company = re.search(
                r"(?:实际)?用工单位[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
                post_region
            )
            if m_company:
                company = m_company.group(1)
            else:
                # pre_region 也搜（中国人寿变动清单的"投保人"标签在 ID 之前的表头）
                m_company_pre = re.search(
                    r"投保人[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
                    pre_region
                )
                if m_company_pre:
                    company = m_company_pre.group(1)
                else:
                    company_match = extract_company_name(post_region + pre_region)
                    if company_match:
                        company = company_match
                    elif policy_holder:
                        company = policy_holder

            # 6. 在身份证号附近提取工种
            #    2026-09-17 增补：中国人寿"被保险人变动清单"无工种列，
            #    需排除"增加主被保险人" / "减少连带被保险人" 等组合词（变动类型+被保险人类型拼接）
            #    2026-09-22 修正：保持 post_region 优先（利宝/太保/华农等工种都在身份证号右边），
            #      仅新增"建筑工"排除（见下）。北部湾"雇主责任险"格式的"备注"列
            #      "建筑工程-建筑公司-油漆工、喷漆工"里也含正确工种"油漆工"，
            #      排除"建筑工程"误匹配的"建筑工"后，post 优先仍能取到"油漆工"。
            job_title = ""
            for region in [post_region, pre_region]:
                if job_title:
                    break
                for job_match in self._JOB_PATTERN.finditer(region):
                    candidate = job_match.group(1)
                    if candidate in self._JOB_BLACKLIST:
                        continue
                    if candidate in self._VARIATION_NOISE:
                        continue
                    # 排除"被保险人"+数字的组合（如"被保险人1"）
                    if re.match(r'^(主|连带|附属)?被保险人\d*$', candidate):
                        continue
                    # 2026-09-17 新增：排除表格表头列名被误匹配的情况
                    # PyMuPDF 把列名拼接成一行 → "被保险人类型" 是匹配 _JOB_PATTERN
                    # 但同时也被算作黑名单（"被保险人"）之外的扩展词
                    if any(kw in candidate for kw in self._TABLE_HEADER_KEYWORDS):
                        continue
                    # 2026-09-22 新增：排除"建筑工程/建筑公司"职业分类路径的"建筑工"误匹配
                    # 例：北部湾"备注"列值"建筑工程-建筑公司-油漆工、喷漆工"中，
                    # _JOB_PATTERN 贪婪匹配"建筑"+"工"→"建筑工"（后跟"程"），
                    # 这是职业分类层级路径的"建筑工程"，不是工种。
                    nxt = region[job_match.end():job_match.end() + 1]
                    if candidate == "建筑工" and nxt == "程":
                        continue
                    job_title = candidate
                    break

            persons.append(InsuredPerson(
                name=name,
                id_number=id_number,
                id_type="身份证",
                company=company,
                start_date=start_date,
                end_date=end_date,
                job_title=job_title,
                birth_date=birth_date,
                confidence=0.85,
                modification_type=mod_type_for_person,
            ))

        return persons

    @classmethod
    def _detect_modification_type(cls, text: str) -> str:
        """从文本中检测批改类型（文件级 fallback）"""
        for marker in cls._REMOVE_MARKERS:
            if marker in text:
                return "减保"
        for marker in cls._ADD_MARKERS:
            if marker in text:
                return "增保"
        return "增保"

    @classmethod
    def _detect_row_modification_type(cls, region: str) -> str:
        """从单行附近检测批改类型（per-row，2026-09-17 新增）

        优先级：
        1. 同期增减/同期替换/同期置换 → 增保（这种格式的PDF「减少被保险人」列
           只显示姓名+编号，没有身份证号 → extractor 只能抓到「增加」一侧）
        2. 替换 / 置换 → 增保（替换 = 减旧 + 增新；DB 只需保留新的人员记录，
           旧记录由其自身 end_date 自然失效）
        3. 减少 / 删除 → 减保
        4. 增加 → 增保

        关键场景：「7月31替换人 (1).pdf」变动类型列值为「同期增减」，
        但 pre_region 也包含列标题「减少被保险人」——必须先匹配「同期增减」，
        否则会被「减少」抢先误判为减保。
        """
        if not region:
            return ""
        # 1. 同期替换/同期增减 优先于「减少」（避免被「减少被保险人」列标题误判）
        if any(m in region for m in cls._SIMULTANEOUS_MARKERS):
            return "增保"
        if any(m in region for m in cls._REPLACE_MARKERS):
            return "增保"
        if any(m in region for m in cls._REMOVE_MARKERS):
            return "减保"
        if any(m in region for m in cls._ADD_MARKERS):
            return "增保"
        return ""
