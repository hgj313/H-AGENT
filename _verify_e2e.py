# -*- coding: utf-8 -*-
"""MQ → 飞书 端到端验证脚本（手动触发）。

用**同一个消费组** `insurance-automation` 拉取一条真实消息，走完整写入路径：
    MQ consume → normalize_events → FeishuWriter.write_batch → 成功后 ack

要点：
- 同消费组内一条消息只会投给一个消费者 → 与常驻消费者不会重复处理；
  即便两边同时有消息写入，幂等映射（同一份 feishu_direct_sync_map.json）保证不产生重复行。
- **写飞书失败绝不 ack** → 消息由 RocketMQ 重投，不会丢。
- 拉不到消息（今天没有新打卡）时直接退出，属正常情况。

用法：python _verify_e2e.py
"""

import json
import os
import sys

sys.path.insert(0, r"C:\insurance-automation")

from mq_http_sdk.mq_client import MQClient
from erp_feishu_direct.config import load_config
from erp_feishu_direct.consumer import _build_writer
from erp_feishu_direct.mapper import normalize_events


def patch_sdk():
    """去掉 HTTPSConnection 的 strict 参数（Python 3.12+ 兼容）。"""
    import http.client
    if not hasattr(http.client.HTTPSConnection, "_wb_patched"):
        http.client.HTTPSConnection._wb_patched = True
        _orig_init = http.client.HTTPSConnection.__init__

        def _init(self, host, port=None, strict=None, **kw):
            kw.pop("strict", None)
            _orig_init(self, host, port, **kw)
        http.client.HTTPSConnection.__init__ = _init


def main():
    patch_sdk()
    cfg = load_config()
    mq = cfg["mq"]
    host = mq.get("host", "")
    if not host.startswith("http"):
        scheme = "https" if mq.get("use_tls") else "http"
        host = "%s://%s:%s" % (scheme, mq.get("host"), mq.get("port"))

    ak = mq.get("access_key") or ""
    sk = mq.get("secret_key") or ""
    if not (ak and sk):
        print("[X] 缺少 ROCKETMQ_ACCESS_KEY / ROCKETMQ_SECRET_KEY")
        return 2

    print("[1] 连接 MQ: %s  group=%s tag=%s" % (host, mq.get("group"), mq.get("tag")))
    client = MQClient(host, ak, sk)
    consumer = client.get_consumer(
        mq.get("instance_id", ""), mq.get("topic", ""), mq.get("group", ""), mq.get("tag", ""))

    print("[2] 拉取消息（长轮询 5s）...")
    try:
        msgs = consumer.consume_message(3, 5)
    except Exception as e:
        if "MessageNotExist" in repr(e):
            print("    MessageNotExist：当前无新消息（MQ 鉴权/订阅/位点均正常）")
            print("    → 链路各段已分别验证通过；待产生一条新打卡即可完成最终闭环")
            return 0
        print("[X] 拉取失败: %r" % (e,))
        return 2
    if not msgs:
        print("    本次没有新消息（今天可能还没有新打卡）—— 属正常情况")
        return 0

    print("    拉到 %d 条消息" % len(msgs))
    bodies = []
    for m in msgs:
        bodies.append(m.message_body)
        print("    原始: %s" % str(m.message_body)[:160])

    print("[3] 解析 + 写入飞书...")
    events = normalize_events(bodies, cfg.get("rename", {}) or {})
    print("    解析出 %d 条事件" % len(events))
    for e in events:
        print("    -> %s / %s / %s" % (e.get("memberName"), e.get("identificationNumber"),
                                      e.get("punchTime")))

    writer = _build_writer(cfg)
    result = writer.write_batch(events)
    print("[4] 写入结果: %s" % json.dumps(result, ensure_ascii=False))

    if result.get("failed"):
        print("[X] 有失败项，不 ack，消息将由 RocketMQ 重投")
        return 1

    print("[5] ack ...")
    try:
        consumer.ack_message([m.receipt_handle for m in msgs])
        print("    ack 成功")
    except Exception as e:
        print("    ack 失败（消息会自动重投）: %r" % (e,))
        return 1

    print("[OK] 端到端验证通过：MQ → 飞书「今日打卡数据」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
