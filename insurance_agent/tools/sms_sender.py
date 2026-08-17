"""短信发送模块

对接短信服务商（阿里云 / 腾讯云），发送保险提醒短信。

当前状态：接口和骨架已就绪，实际 SDK 调用待提供服务商凭证后填充。

短信模板见 insurance_reminder.py 的 SMS_TEMPLATE / SMS_TEMPLATE_VARS。
"""

import logging

logger = logging.getLogger(__name__)


def send_sms(sms_config: dict, messages: list[dict]) -> dict:
    """发送短信提醒

    Args:
        sms_config: sms 配置，字段：
            provider: "aliyun" / "tencent"
            access_key_id / access_key_secret: 服务商密钥
            sdk_app_id: 腾讯云专用
            sign_name: 短信签名
            template_code: 短信模板 Code
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
    if not sms_config.get("template_code"):
        return {"success": False, "message": "未配置短信模板 Code", "sent_count": 0}
    if not sms_config.get("sign_name"):
        return {"success": False, "message": "未配置短信签名", "sent_count": 0}
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
    except Exception as e:
        logger.error("短信发送异常: %s", e, exc_info=True)
        return {"success": False, "message": f"短信发送失败: {e}", "sent_count": 0}


def _send_aliyun(sms_config: dict, messages: list[dict], phone_numbers: list[str]) -> dict:
    """阿里云短信发送（TODO：待提供服务商凭证后实现 SDK 调用）

    阿里云短信 API：
    - 端点: dysmsapi.aliyuncs.com
    - 参数: PhoneNumbers, SignName, TemplateCode, TemplateParam(JSON)
    - TemplateParam 例: {"project": "...", "names": "...", "count": "..."}
    """
    # TODO: 对接阿里云短信 SDK 或 HTTP 签名调用
    # 需要: access_key_id, access_key_secret, sign_name, template_code
    return {
        "success": False,
        "message": "阿里云短信发送待实现（需提供服务商凭证后对接 SDK）",
        "sent_count": 0,
    }


def _send_tencent(sms_config: dict, messages: list[dict], phone_numbers: list[str]) -> dict:
    """腾讯云短信发送（TODO：待提供服务商凭证后实现 SDK 调用）

    腾讯云短信 API：
    - SDKAppID, SecretId, SecretKey
    - 参数: PhoneNumberSet, SmsSdkAppId, SignName, TemplateId, TemplateParamSet(数组)
    - TemplateParamSet 例: [project, names, count]（按模板变量顺序）
    """
    # TODO: 对接腾讯云短信 SDK（tencentcloud-sdk-python）
    # 需要: access_key_id(SecretId), access_key_secret(SecretKey), sdk_app_id, sign_name, template_code
    return {
        "success": False,
        "message": "腾讯云短信发送待实现（需提供服务商凭证后对接 SDK）",
        "sent_count": 0,
    }
