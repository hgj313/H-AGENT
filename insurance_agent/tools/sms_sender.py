"""短信发送模块

对接短信服务商（阿里云 / 腾讯云），发送保险提醒短信。

设计原则：所有配置参数（服务商 / 密钥 / 签名 / 模板 / 应用ID / 区域 / 接收号）
均来自调用方传入的 sms_config（最终来源于前端「手机短信通知配置」填写并保存到
.reminder_config.json），后台不写死任何凭证或区域，保证用户可灵活配置。

短信模板见 insurance_reminder.py 的 SMS_TEMPLATE / SMS_TEMPLATE_VARS。
"""

import base64
import datetime
import hashlib
import hmac
import json
import logging
import time
import uuid
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# 区域缺省值（仅当配置未填写时生效，用户可在前端覆盖）
_ALIYUN_DEFAULT_REGION = "cn-hangzhou"
_TENCENT_DEFAULT_REGION = "ap-guangzhou"


# ============ 阿里云 RPC 签名 (HMAC-SHA1) ============

def _aliyun_percent_encode(text: str) -> str:
    """阿里云规范要求的 URL 编码（RFC3986 变体）"""
    return (
        quote(str(text), safe="")
        .replace("+", "%20")
        .replace("*", "%2A")
        .replace("%7E", "~")
    )


def _aliyun_sign(access_key_secret: str, params: dict) -> str:
    """对参数集合做阿里云 RPC 签名。

    Args:
        access_key_secret: 阿里云 AccessKey Secret
        params: 所有公共参数 + 业务参数（不含 Signature 本身）
    Returns:
        Base64 编码的 HMAC-SHA1 签名串
    """
    canonical = "&".join(
        f"{_aliyun_percent_encode(k)}={_aliyun_percent_encode(v)}"
        for k, v in sorted(params.items())
    )
    string_to_sign = (
        "GET&" + _aliyun_percent_encode("/") + "&" + _aliyun_percent_encode(canonical)
    )
    key = (access_key_secret + "&").encode("utf-8")
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


# ============ 腾讯云 TC3-HMAC-SHA256 签名 ============

def _tencent_tc3_sign(
    secret_id: str,
    secret_key: str,
    service: str,
    host: str,
    action: str,
    version: str,
    region: str,
    payload: str,
    timestamp: int,
) -> str:
    """腾讯云 TC3-HMAC-SHA256 签名，返回 Authorization 头值。"""
    content_type = "application/json; charset=utf-8"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join([
        "POST",
        "/",
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256",
        str(timestamp),
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


# ============ 对外发送入口 ============

def send_sms(sms_config: dict, messages: list[dict]) -> dict:
    """发送短信提醒

    所有参数均来自 sms_config（前端配置 → .reminder_config.json），后台不写死。

    Args:
        sms_config: 短信配置，字段：
            provider: "aliyun" / "tencent"
            access_key_id / access_key_secret: 服务商密钥
            sdk_app_id: 腾讯云专用
            sign_name: 短信签名
            template_code: 短信模板 Code / TemplateId
            region: 区域（可选，缺省按服务商默认）
            phone_numbers: 接收手机号列表
        messages: build_sms_messages 返回的模板变量列表
                  [{"project": ..., "names": ..., "count": ...}, ...]

    Returns:
        {"success": bool, "message": str, "sent_count": int}
    """
    if not messages:
        return {"success": True, "message": "无需发送短信", "sent_count": 0}

    phone_numbers = sms_config.get("phone_numbers", [])
    if isinstance(phone_numbers, str):
        phone_numbers = [p.strip() for p in phone_numbers.split(",") if p.strip()]

    if not phone_numbers:
        return {"success": False, "message": "未配置接收手机号", "sent_count": 0}
    if not sms_config.get("access_key_id") or not sms_config.get("access_key_secret"):
        return {"success": False, "message": "未配置短信服务商密钥", "sent_count": 0}

    provider = sms_config.get("provider", "aliyun")
    try:
        if provider == "aliyun":
            return _send_aliyun(sms_config, messages, phone_numbers)
        elif provider == "tencent":
            return _send_tencent(sms_config, messages, phone_numbers)
        else:
            return {"success": False, "message": f"不支持的短信服务商: {provider}", "sent_count": 0}
    except Exception as e:  # noqa: BLE001
        logger.error("短信发送异常: %s", e, exc_info=True)
        return {"success": False, "message": f"短信发送失败: {e}", "sent_count": 0}


def _send_aliyun(sms_config: dict, messages: list[dict], phone_numbers: list[str]) -> dict:
    """阿里云短信发送（RPC + HMAC-SHA1 签名，无需安装 SDK）"""
    access_key_id = sms_config.get("access_key_id", "")
    access_key_secret = sms_config.get("access_key_secret", "")
    sign_name = sms_config.get("sign_name", "")
    template_code = sms_config.get("template_code", "")
    region = sms_config.get("region") or _ALIYUN_DEFAULT_REGION

    if not sign_name:
        return {"success": False, "message": "未配置短信签名(SignName)，请在前端填写", "sent_count": 0}
    if not template_code:
        return {"success": False, "message": "未配置短信模板 Code", "sent_count": 0}

    endpoint = "https://dysmsapi.aliyuncs.com"
    phone_str = ",".join(phone_numbers)

    sent_count = 0
    errors: list[str] = []

    for msg in messages:
        template_param = json.dumps(msg, ensure_ascii=False)
        params = {
            "AccessKeyId": access_key_id,
            "Action": "SendSms",
            "Format": "JSON",
            "RegionId": region,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2017-05-25",
            "PhoneNumbers": phone_str,
            "SignName": sign_name,
            "TemplateCode": template_code,
            "TemplateParam": template_param,
        }
        params["Signature"] = _aliyun_sign(access_key_secret, params)

        # 使用与签名一致的编码手工拼接待签名查询串，避免 requests 二次编码差异
        query = "&".join(
            f"{_aliyun_percent_encode(k)}={_aliyun_percent_encode(v)}"
            for k, v in sorted(params.items())
        )
        url = f"{endpoint}?{query}"

        try:
            resp = requests.get(url, timeout=15)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            errors.append(f"请求失败: {e}")
            continue

        code = data.get("Code")
        if code == "OK":
            sent_count += 1
            logger.info("阿里云短信发送成功: %s", data.get("BizId"))
        else:
            errors.append(data.get("Message") or code or "未知错误")

    if sent_count:
        return {
            "success": True,
            "message": f"已发送 {sent_count}/{len(messages)} 条短信",
            "sent_count": sent_count,
        }
    return {"success": False, "message": "；".join(errors) or "发送失败", "sent_count": 0}


def _send_tencent(sms_config: dict, messages: list[dict], phone_numbers: list[str]) -> dict:
    """腾讯云短信发送（TC3-HMAC-SHA256 签名，无需安装 SDK）

    注意：腾讯云模板变量为「位置顺序」数组（TemplateParamSet），此处按 message
    字典插入顺序取值传入；请确保前端模板变量顺序与 message 字段顺序一致。
    """
    secret_id = sms_config.get("access_key_id", "")
    secret_key = sms_config.get("access_key_secret", "")
    sdk_app_id = sms_config.get("sdk_app_id", "")
    sign_name = sms_config.get("sign_name", "")
    template_id = sms_config.get("template_code", "")
    region = sms_config.get("region") or _TENCENT_DEFAULT_REGION

    if not sdk_app_id:
        return {"success": False, "message": "未配置 SDKAppID（腾讯云）", "sent_count": 0}
    if not sign_name:
        return {"success": False, "message": "未配置短信签名(SignName)", "sent_count": 0}
    if not template_id:
        return {"success": False, "message": "未配置短信模板 ID(TemplateId)", "sent_count": 0}

    service = "sms"
    host = "sms.tencentcloudapi.com"
    endpoint = f"https://{host}"
    action = "SendSms"
    version = "2021-01-11"

    # 手机号需带国家码前缀
    phone_set = [
        (f"+86{p}" if not p.startswith("+") else p) for p in phone_numbers
    ]

    sent_count = 0
    errors: list[str] = []

    for msg in messages:
        param_set = [str(v) for v in msg.values()]
        payload_obj = {
            "PhoneNumberSet": phone_set,
            "SmsSdkAppId": sdk_app_id,
            "SignName": sign_name,
            "TemplateId": template_id,
            "TemplateParamSet": param_set,
        }
        payload = json.dumps(payload_obj)
        timestamp = int(time.time())

        authorization = _tencent_tc3_sign(
            secret_id, secret_key, service, host, action, version, region, payload, timestamp
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
            "X-TC-Region": region,
        }

        try:
            resp = requests.post(endpoint, headers=headers, data=payload, timeout=15)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            errors.append(f"请求失败: {e}")
            continue

        resp_data = data.get("Response", {})
        err = resp_data.get("Error")
        if err:
            errors.append(err.get("Message") or err.get("Code") or "未知错误")
        else:
            sent_count += 1
            logger.info("腾讯云短信发送成功: %s", resp_data.get("SendStatusSet"))

    if sent_count:
        return {
            "success": True,
            "message": f"已发送 {sent_count}/{len(messages)} 条短信",
            "sent_count": sent_count,
        }
    return {"success": False, "message": "；".join(errors) or "发送失败", "sent_count": 0}
