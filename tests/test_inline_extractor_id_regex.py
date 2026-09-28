"""回归测试：完整 18 位 ID 和脱敏 ID 都能被 inline_extractor 提取"""
import sys
sys.path.insert(0, '.')

cases = [
    # (描述, 输入文本, 期望人员列表[(姓名,ID,工种,公司,增/减)])
    ("完整18位ID（崇茂劳务丁德富）",
     "<<增加人员信息明细>>，共计：1人\n雇员姓名：丁德富，证件号：510228196705309118，方案序号：5，工种描述：砌筑工，用工单位：重庆崇茂劳务有限公司，保费计(CNY)：178.00；",
     [("丁德富", "510228196705309118", "砌筑工", "重庆崇茂劳务有限公司", "增保")]),
    ("脱敏ID（平安养老模板）",
     "<<增加人员信息明细>>\n雇员姓名：张三，证件号：412702********2432，工种描述：建筑工，用工单位：测试公司",
     [("张三", "412702********2432", "建筑工", "测试公司", "增保")]),
    ("多个完整ID（利宝批单多增保人）",
     "<<增加人员信息明细>>，共计：2人\n雇员姓名：丁德富，证件号：510228196705309118，方案序号：5，工种描述：砌筑工，用工单位：重庆崇茂劳务有限公司；\n雇员姓名：李四，证件号：510228197001011234，方案序号：5，工种描述：木工，用工单位：重庆崇茂劳务有限公司；",
     [("丁德富", "510228196705309118", "砌筑工", "重庆崇茂劳务有限公司", "增保"),
      ("李四", "510228197001011234", "木工", "重庆崇茂劳务有限公司", "增保")]),
    ("混合：删除+增加",
     "删除雇员信息为：\n雇员姓名：王五，证件号：510228198001011234，工种描述：电工，用工单位：测试公司；\n增加雇员信息为：\n雇员姓名：丁德富，证件号：510228196705309118，工种描述：砌筑工，用工单位：测试公司",
     [("王五", "510228198001011234", "电工", "测试公司", "减保"),
      ("丁德富", "510228196705309118", "砌筑工", "测试公司", "增保")]),
    ("多增保人含 1 完整ID + 1 脱敏ID",
     "<<增加人员信息明细>>，共计：2人\n雇员姓名：丁德富，证件号：510228196705309118，方案序号：5，工种描述：砌筑工，用工单位：测试公司；\n雇员姓名：张三，证件号：412702********2432，方案序号：5，工种描述：建筑工，用工单位：测试公司；",
     [("丁德富", "510228196705309118", "砌筑工", "测试公司", "增保"),
      ("张三", "412702********2432", "建筑工", "测试公司", "增保")]),
]

from insurance_agent.extractors.inline_extractor import InlineExtractor
extractor = InlineExtractor()
passed = 0
failed = 0
for desc, text, expected_persons in cases:
    company = expected_persons[0][3] if expected_persons else ""
    persons = extractor.extract(text, policy_holder=company, insurance_company="利宝保险")
    if len(persons) != len(expected_persons):
        print(f"❌ [{desc}] 实际提取 {len(persons)} 人，期望 {len(expected_persons)}")
        for p in persons:
            print(f"     {p.name} | {p.id_number} | {p.job_title} | {p.company} | {p.modification_type}")
        failed += 1
        continue
    all_ok = True
    for p, (exp_name, exp_id, exp_job, exp_company, exp_mod) in zip(persons, expected_persons):
        if (p.name != exp_name or p.id_number != exp_id or p.job_title != exp_job or p.company != exp_company or p.modification_type != exp_mod):
            print(f"   ✗ 不匹配: 实际 {p.name} | {p.id_number} | {p.job_title} | {p.company} | {p.modification_type}")
            print(f"           期望 {exp_name} | {exp_id} | {exp_job} | {exp_company} | {exp_mod}")
            all_ok = False
    if all_ok:
        print(f"✅ [{desc}] 提取 {len(persons)} 人:")
        for p in persons:
            print(f"     {p.name} | {p.id_number} | {p.job_title} | {p.company} | {p.modification_type}")
        passed += 1
    else:
        print(f"❌ [{desc}]")
        failed += 1

print()
print(f"通过: {passed}/{len(cases)} | 失败: {failed}/{len(cases)}")
sys.exit(0 if failed == 0 else 1)
