"""直连链路独立自检脚本（**不依赖 8765 服务**，可单独运行）

用途
----
飞书端的「应用权限」与「文档权限」是两层独立拦截，只看代码无法确认是否配置正确。
本脚本按「配置 → 鉴权 → 表结构 → 字段对齐 → 消费组」逐项体检，
在你启动消费者**之前**把飞书侧的问题一次性暴露出来。

用法::

    # 项目根目录执行（mq_http_sdk 只装在 H-AGENT venv 里）
    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.probe

    # 额外做一次「写 → 读 → 删」的真实写入验证
    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.probe --write-test

    # 机器可读输出
    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.probe --json

检查项
------
1. 配置文件 / 环境变量是否齐备（缺哪些 key）
2. 飞书 tenant_access_token 能否取到（app_id + app_secret 是否正确）
3. app_token 是否有效、能否列出数据表（**文档权限**是否已通过「添加文档应用」授予）
4. 目标数据表能否定位（table_id / table_name）
5. 表字段是否与映射表对齐，日期列类型是否正确（**类型错了写入时报 1254064**）
6. RocketMQ 消费组是否已在阿里云控制台创建（只读查询，**不消费消息**）
7. `--write-test`：写一条测试记录 → 读回 → 删除，验证写权限
"""

import argparse
import json
import logging
import sys
import time
from typing import Any, Dict, List, Optional

from insurance_agent.infrastructure.feishu_bitable_client import (
    FeishuBitableClient,
    FeishuBitableError,
    load_client_from_config,
)

from erp_feishu_direct.config import load_config, missing_keys
from erp_feishu_direct.mapper import DATE_FIELDS, NUMBER_FIELDS, build_fields

logger = logging.getLogger("erp_feishu_direct.probe")

# 飞书多维表格字段类型枚举（只列与本链路相关的）
FIELD_TYPE_TEXT = 1
FIELD_TYPE_NUMBER = 2
FIELD_TYPE_DATE = 5

_TYPE_LABEL = {
    1: "文本",
    2: "数字",
    3: "单选",
    4: "多选",
    5: "日期",
    7: "复选框",
    11: "人员",
    13: "电话",
    15: "超链接",
    17: "附件",
    20: "公式",
    22: "地理位置",
    1001: "创建时间",
    1002: "修改时间",
}

# 写测试用的假身份证号（不会与真实数据冲突）
_PROBE_ID = "000000199001010000"
_PROBE_NAME = "__probe_selfcheck__"

# 保险AI助手现有 MQ 桥接正在使用的消费组（实测生效的那个）。
# ⚠️ 直连链路绝不能复用这里的组名 —— 同组会互相抢消息，各自只收到一半。
# ⚠️ 历史文档里写成 GID_INSURANCE_AGENT_PROCESS 是错的，实测该组并不存在；
#    桥接日志里的真实组名是 `insurance-automation`。
_BRIDGE_GROUPS = {"insurance-automation", "GID_INSURANCE_AGENT_PROCESS"}


class Checker:
    """自检结果收集器"""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, level: str, title: str, detail: str = "") -> None:
        self.items.append({"level": level, "title": title, "detail": detail})
        icon = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]", "info": "[INFO]"}.get(level, "[INFO]")
        print(f"{icon} {title}" + (f"\n       {detail}" if detail else ""))

    @property
    def has_error(self) -> bool:
        return any(i["level"] == "error" for i in self.items)

    def summary(self) -> Dict[str, int]:
        out = {"ok": 0, "warn": 0, "error": 0, "info": 0}
        for i in self.items:
            out[i["level"]] = out.get(i["level"], 0) + 1
        return out


# ==================== 飞书侧 ====================


def check_feishu(cfg: Dict[str, Any], ck: Checker) -> Optional[FeishuBitableClient]:
    """检查飞书鉴权与表结构，返回可用的客户端"""
    fs = cfg["feishu"]
    client = load_client_from_config(fs)

    # 1) token
    try:
        client.get_token()
        ck.add("ok", "飞书鉴权成功", f"app_id={fs.get('app_id', '')}")
    except FeishuBitableError as e:
        ck.add(
            "error",
            "飞书鉴权失败",
            f"code={e.code} msg={e.msg}\n"
            "       → 检查 FEISHU_APP_ID / FEISHU_APP_SECRET 是否正确"
            "（10003 app_id 不存在 / 10029 app_secret 不匹配 / 99991663 token 无效）",
        )
        return None
    except Exception as e:  # noqa: BLE001
        ck.add("error", "飞书鉴权异常", repr(e))
        return None

    # 2) app_token + 数据表列表
    try:
        tables = client.list_tables()
    except FeishuBitableError as e:
        hint = ""
        if e.code in (1254002, 1254043, 91402):
            hint = (
                "\n       → app_token 无效或应用无权限访问该表格。"
                "\n       → 多维表格页面「...」→「...更多」→「添加文档应用」，把应用加为**可管理**协作者"
            )
        elif e.code == 99991431:
            hint = "\n       → 应用没有多维表格 API 权限（权限管理里申请 bitable:app 并**发布版本**）"
        ck.add("error", f"读取多维表格失败 code={e.code}", f"{e.msg}{hint}")
        return None
    except Exception as e:  # noqa: BLE001
        ck.add("error", "读取多维表格异常", repr(e))
        return None

    if not tables:
        ck.add("error", "多维表格里没有任何数据表", "请先在多维表格中新建一张数据表")
        return None

    ck.add("ok", f"app_token 有效，共 {len(tables)} 张数据表",
           "、".join(f"{t.get('name')}({t.get('table_id')})" for t in tables))

    # 3) 定位目标表
    table_id = fs.get("table_id") or ""
    table_name = fs.get("table_name") or ""

    if not table_id and table_name:
        try:
            table_id = client.resolve_table_id(table_name)
            ck.add("ok", f"按名称定位数据表「{table_name}」", f"table_id={table_id}")
        except ValueError as e:
            ck.add("error", "按名称找不到数据表", str(e))
            return None
    elif not table_id and len(tables) == 1:
        table_id = tables[0].get("table_id", "")
        ck.add("ok", f"自动选用唯一数据表「{tables[0].get('name')}」", f"table_id={table_id}")
    elif not table_id:
        ck.add("error", "无法确定目标数据表",
               f"请在配置里设置 feishu.table_id 或 feishu.table_name；现有表："
               + "、".join(f"{t.get('name')}({t.get('table_id')})" for t in tables))
        return None
    else:
        ck.add("ok", "使用配置中的 table_id", f"table_id={table_id}")

    client._table_id = table_id  # noqa: SLF001 —— 后续检查复用

    # 4) 字段对齐
    try:
        fields = client.list_fields(table_id)
    except FeishuBitableError as e:
        ck.add("error", f"读取表字段失败 code={e.code}", e.msg)
        return client

    actual = {f.get("field_name"): f for f in fields}
    ck.add("info", f"表内共 {len(actual)} 个字段",
           "、".join(f"{n}({_TYPE_LABEL.get(a.get('type'), a.get('type'))})" for n, a in actual.items()))

    from erp_feishu_direct.mapper import DEFAULT_FIELD_MAPPING

    missing = [c for c in DEFAULT_FIELD_MAPPING if c not in actual]
    if missing:
        ck.add("error", "多维表格缺少映射所需的列",
               f"缺失 {len(missing)} 列：{'、'.join(missing)}\n"
               "       → 写入时会报 1254045 FieldNameNotFound。请在多维表格里补齐这些列")
    else:
        ck.add("ok", "映射所需的 13 列全部存在")

    # 日期列类型检查（类型不对写入时报 1254064）
    for col in DEFAULT_FIELD_MAPPING:
        if col not in actual:
            continue
        ftype = actual[col].get("type")
        if col in DATE_FIELDS and ftype != FIELD_TYPE_DATE:
            ck.add("error", f"列「{col}」类型错误",
                   f"当前是「{_TYPE_LABEL.get(ftype, ftype)}」，必须是「日期」，"
                   "否则写入报 1254064（日期列只接受 13 位毫秒时间戳）")
        elif col in NUMBER_FIELDS and ftype != FIELD_TYPE_NUMBER:
            ck.add("error", f"列「{col}」类型错误",
                   f"当前是「{_TYPE_LABEL.get(ftype, ftype)}」，必须是「数字」")
        elif col not in DATE_FIELDS and col not in NUMBER_FIELDS:
            if ftype in (3, 4):
                ck.add("warn", f"列「{col}」是「{_TYPE_LABEL.get(ftype, ftype)}」类型",
                       "映射层写入的是字符串，若该单选/多选的选项里没有对应值会报 1254062")

    extra = [c for c in actual if c not in DEFAULT_FIELD_MAPPING and not c.startswith("创建")
             and not c.startswith("修改")]
    if extra:
        ck.add("info", "表内有多余列（不会被写入，不影响同步）", "、".join(extra))

    return client


def check_write_permission(client: FeishuBitableClient, ck: Checker) -> None:
    """写测试：写一条 → 读回 → 删除"""
    event = {
        "memberName": _PROBE_NAME,
        "identificationNumber": _PROBE_ID,
        "punchTime": int(time.time() * 1000),
    }
    try:
        fields = build_fields(event)
    except Exception as e:  # noqa: BLE001
        ck.add("error", "构造测试字段失败", repr(e))
        return

    record_id = ""
    try:
        created = client.batch_create([{"fields": fields}])
        if not created or not created[0].get("record_id"):
            ck.add("error", "写入测试失败", "接口返回成功但没有 record_id")
            return
        record_id = created[0]["record_id"]
        ck.add("ok", "写入测试成功", f"record_id={record_id}")

        # 用精确读取核对字段回填
        data = client._request(  # noqa: SLF001
            "GET", f"/bitable/v1/apps/{client._app_token}/tables/{client._table_id}/records"  # noqa: SLF001
        )
        items = data.get("items") or []
        mine = [r for r in items if r.get("record_id") == record_id]
        if mine:
            got = mine[0].get("fields") or {}
            ck.add("ok", "读回校验成功",
                   f"姓名={got.get('姓名')} 打卡时间={got.get('打卡时间')} 打卡日期={got.get('打卡日期')}")
        else:
            ck.add("warn", "读回未找到刚写入的记录", "可能分页未覆盖，稍后手动确认")

    except FeishuBitableError as e:
        hint = ""
        if e.code == 1254045:
            hint = "\n       → 表里缺少同名列，检查上方「缺少映射所需的列」"
        elif e.code == 1254064:
            hint = "\n       → 日期列类型不对，必须是「日期」类型"
        elif e.code == 1254062:
            hint = "\n       → 单选/多选列的选项里没有该值"
        elif e.code in (1254002, 91402):
            hint = "\n       → 应用没有该多维表格的文档权限，去页面「添加文档应用」加为可管理"
        ck.add("error", f"写入测试失败 code={e.code}", f"{e.msg}{hint}")
    except Exception as e:  # noqa: BLE001
        ck.add("error", "写入测试异常", repr(e))
    finally:
        # 无论成败都清理测试记录
        if record_id:
            try:
                client.batch_delete([record_id])
                ck.add("ok", "测试记录已清理", f"已删除 {record_id}")
            except Exception as e:  # noqa: BLE001
                ck.add("warn", "测试记录清理失败", f"{record_id} 请手动删除。原因: {e}")


# ==================== MQ 侧 ====================


def check_mq(cfg: Dict[str, Any], ck: Checker) -> None:
    """检查 RocketMQ 消费组是否已在阿里云控制台创建

    为什么不用 ``/consumer/groupStatus``
    ----------------------------------
    该接口是**管理级**接口，需要实例 Owner 权限；用消息消费的 AK 调用会固定返回
    403 ``The OwnerId that your Access Key Id associated to is forbidden``，
    无法区分「组不存在」和「AK 没权限」，是个假信号。

    实际做法
    --------
    直接打消费端点 ``GET /topics/{topic}/messages``：
    - **404 MessageNotExist** → 消费组已存在（404 只是「当前没有消息」，不是错误）
    - **403 AccessDenied ... not created** → 消费组尚未在阿里云控制台创建

    风险控制
    --------
    组存在时可能真的拉到 1 条消息。此时**不 ack**（ack 掉就丢了），
    RocketMQ 会在不可见期后把同一条消息重投给该消费组，由正式消费者处理。
    """
    mq = cfg["mq"]
    group = mq["group"]

    # 与现有桥接组重名会互相抢消息 → 致命配置错误，必须拦下
    if group in _BRIDGE_GROUPS:
        ck.add("error", "消费组与现有 MQ 桥接重名",
               f"group={group} 是保险AI助手桥接正在使用的消费组。\n"
               "       → 同一消费组内会互相抢消息，各自只收到一半。"
               "直连链路必须使用**另一个**消费组")
        return

    try:
        from mq_http_sdk.mq_client import MQClient
        from mq_http_sdk.mq_http import RequestInternal
    except ImportError:
        ck.add("error", "未安装 mq_http_sdk",
               "请用 H-AGENT\\.venv\\Scripts\\python.exe 运行（该 SDK 只装在那个 venv 里）")
        return

    from erp_feishu_direct.consumer import _patch_mq_http_sdk_compat

    _patch_mq_http_sdk_compat()

    host = mq.get("host", "")
    if not host.startswith("http"):
        scheme = "https" if mq.get("use_tls") else "http"
        host = f"{scheme}://{host}" + (f":{mq['port']}" if mq.get("port") else "")

    client = MQClient(host, mq["access_key"], mq["secret_key"])

    # 探活请求：只取 1 条、最长等 1 秒，尽量少占用
    uri = (
        f"/topics/{mq['topic']}/messages?consumer={group}"
        f"&numOfMessages=1&ns={mq.get('instance_id', '')}&waitseconds=1"
    )
    if mq.get("tag"):
        uri += f"&tag={mq['tag']}"

    try:
        req_inter = RequestInternal("GET", uri)
        client.build_header(None, req_inter)  # req 参数在 SDK 内部未被使用
        resp = client.http.send_request(req_inter)

        body = resp.data.decode("utf-8", "replace") if isinstance(resp.data, bytes) else (resp.data or "")
        code = body.split("<Code>")[1].split("</Code>")[0] if "<Code>" in body else ""
        message = body.split("<Message>")[1].split("</Message>")[0] if "<Message>" in body else ""

        if resp.status == 404 or code == "MessageNotExist":
            ck.add("ok", "RocketMQ 消费组已存在",
                   f"group={group}\n"
                   f"       topic={mq['topic']} tag={mq.get('tag') or '(全部)'}")
        elif "AccessDenied" in (code + message) or "not created" in message:
            ck.add("error", "RocketMQ 消费组尚未创建",
                   f"group={group} → {code}: {message}\n"
                   "       → 阿里云 RocketMQ 控制台 → 消费者组 → 新建消费组 "
                   f"「{group}」，订阅 tag 填 {mq.get('tag') or '(全部)'}")
        elif 200 <= resp.status < 400:
            ck.add("ok", "RocketMQ 消费组已存在",
                   f"group={group}（探活时拉到 1 条消息，未 ack，稍后会重投给消费者）")
        else:
            ck.add("error", f"RocketMQ 消费组探测异常 HTTP {resp.status}",
                   f"{code}: {message}")

    except Exception as e:  # noqa: BLE001
        ck.add("warn", "RocketMQ 消费组探测异常", repr(e))


# ==================== 入口 ====================


def main() -> int:
    parser = argparse.ArgumentParser(description="ERP→飞书直连链路自检")
    parser.add_argument("--write-test", action="store_true", help="执行一次真实的写→读→删验证")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--skip-mq", action="store_true", help="跳过 RocketMQ 检查")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    ck = Checker()

    if not args.json:
        print("=" * 66)
        print("ERP → 飞书多维表格 直连链路自检")
        print("=" * 66)

    # 1) 配置
    cfg = load_config()
    missing = missing_keys(cfg)
    if missing:
        ck.add("error", "缺少必要凭证",
               f"{'、'.join(missing)}\n"
               "       → 在项目根目录 .env 中补齐（也可写进 erp_feishu_direct_config.json）")
    else:
        ck.add("ok", "凭证齐备", "RocketMQ AK/SK、飞书 app_id/app_secret/app_token 均已配置")

    # 2) 飞书（缺凭证时跳过，但不影响后面的 MQ 检查 —— 一次跑完拿全量结论）
    client = None
    if missing:
        ck.add("warn", "跳过飞书侧检查", "凭证不全，无法验证 app_token / 表结构 / 写权限")
    else:
        client = check_feishu(cfg, ck)

    # 3) 写入权限
    if client is not None and args.write_test:
        check_write_permission(client, ck)

    # 4) MQ（与飞书凭证无关，独立检查）
    if not args.skip_mq:
        mq_missing = [k for k in missing if "FEISHU" not in k]
        if mq_missing:
            ck.add("warn", "跳过 RocketMQ 检查", f"缺少 {'、'.join(mq_missing)}")
        else:
            check_mq(cfg, ck)

    summary = ck.summary()
    code = 1 if ck.has_error else 0

    if args.json:
        print(json.dumps(
            {"ok": code == 0, "summary": summary, "items": ck.items},
            ensure_ascii=False, indent=2,
        ))
    else:
        print("=" * 66)
        print(f"自检结果：{'全部通过' if code == 0 else '存在问题'} "
              f"| 通过 {summary['ok']} / 警告 {summary['warn']} / 错误 {summary['error']}")
        if not args.write_test and client is not None:
            print("提示：加 --write-test 可验证写权限（会写一条测试记录后自动删除）")
        print("=" * 66)

    return code


if __name__ == "__main__":
    sys.exit(main())
