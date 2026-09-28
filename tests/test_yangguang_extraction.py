"""阳光保险格式回归测试（2026-09-28 新增）"""
import sys
sys.path.insert(0, '.')

cases = [
    # (描述, 文本, extractor, policy_holder, 期望结果[(姓名,ID,工种,公司,增/减)])
    ("阳光保单-管工（无括号）",
     "人员清单\n序号\n姓名\n证件类型\n证件号码\n出生日期\n职业类别\n受益人\n1\n张三\n身份证\n510222196601095516\n1966-01-09\n管工\n法定",
     "table",
     "重庆域豹建筑安装工程有限公司",
     [("张三", "510222196601095516", "管工", "重庆域豹建筑安装工程有限公司", "增保")]),
    ("阳光保单-水电工（非涉高）带括号",
     "人员清单\n序号\n姓名\n证件类型\n证件号码\n出生日期\n职业类别\n受益人\n1\n李四\n身份证\n510222196601095517\n1966-01-09\n水电工（非涉高）\n法定",
     "table",
     "重庆域豹建筑安装工程有限公司",
     [("李四", "510222196601095517", "水电工（非涉高）", "重庆域豹建筑安装工程有限公司", "增保")]),
    ("阳光保单-多增保人含括号+无括号",
     "人员清单\n序号\n姓名\n证件类型\n证件号码\n出生日期\n职业类别\n受益人\n1\n张三\n身份证\n510222196601095516\n1966-01-09\n管工\n法定\n2\n李四\n身份证\n510222196601095517\n1966-01-09\n水电工（非涉高）\n法定",
     "table",
     "重庆域豹建筑安装工程有限公司",
     [("张三", "510222196601095516", "管工", "重庆域豹建筑安装工程有限公司", "增保"),
      ("李四", "510222196601095517", "水电工（非涉高）", "重庆域豹建筑安装工程有限公司", "增保")]),
    ("阳光批单-3人inline",
     "《增加被保人》\n被保险人姓名:杨仕亮,证件号码:522224196607232434,\n被保险人姓名:李世全,证件号码:510232196509148016,\n被保险人姓名:杨飞,证件号码:522224199708152437,",
     "inline",
     "",
     [("杨仕亮", "522224196607232434", "", "", "增保"),
      ("李世全", "510232196509148016", "", "", "增保"),
      ("杨飞", "522224199708152437", "", "", "增保")]),
    ("条款段含'批减/减少/注销'不应误判减保（关键回归测试）",
     # 阳光保单条款段 #3 已有"已发生理赔的人员不可以被替换和批减"
     # 文件级 fallback 应识别为增保（无"本次批改合计/本期新增"等强证据）
     "本合同为记名投保...已发生理赔的人员不可以被替换和批减。\n人员减少或退保...人员清单\n1\n王五\n身份证\n510222196601095518\n1966-01-09\n管工\n法定",
     "table",
     "重庆某公司",
     [("王五", "510222196601095518", "管工", "重庆某公司", "增保")]),
    ("利宝批单-回归（确认未破坏既有格式）",
     "本次批改合计批增: 1人\n增加人员信息明细>>，共计：1人\n雇员姓名：张三，证件号：510228196705309118，方案序号：5，工种描述：砌筑工，用工单位：测试公司",
     "inline",
     "测试公司",
     [("张三", "510228196705309118", "砌筑工", "测试公司", "增保")]),
]

from insurance_agent.extractors.table_extractor import TableExtractor
from insurance_agent.extractors.inline_extractor import InlineExtractor
table_ext = TableExtractor()
inline_ext = InlineExtractor()

passed = 0
failed = 0
for desc, text, fmt, policy_holder, expected_persons in cases:
    if fmt == "table":
        persons = table_ext.extract(text, policy_holder=policy_holder, insurance_company="阳光保险")
    else:
        persons = inline_ext.extract(text, policy_holder=policy_holder, insurance_company="阳光保险")
    if len(persons) != len(expected_persons):
        print(f"❌ [{desc}] 实际 {len(persons)} 人，期望 {len(expected_persons)}")
        failed += 1
        continue
    all_ok = True
    for p, (exp_name, exp_id, exp_job, exp_company, exp_mod) in zip(persons, expected_persons):
        if (p.name != exp_name or p.id_number != exp_id or p.job_title != exp_job
            or p.company != exp_company or p.modification_type != exp_mod):
            print(f"   ✗  {p.name} | {p.id_number} | {p.job_title!r} | {p.company!r} | {p.modification_type}")
            print(f"        vs {exp_name} | {exp_id} | {exp_job!r} | {exp_company!r} | {exp_mod}")
            all_ok = False
    if all_ok:
        print(f"✅ [{desc}]")
        passed += 1
    else:
        print(f"❌ [{desc}]")
        failed += 1

print()
print(f"通过: {passed}/{len(cases)} | 失败: {failed}/{len(cases)}")
sys.exit(0 if failed == 0 else 1)
