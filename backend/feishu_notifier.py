"""
飞书机器人通知模块：批量/单条解析完成后发送通知到飞书群
"""
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

logger = logging.getLogger("feishu_notifier")


def _get_webhook_url() -> str:
    """获取配置的 webhook URL（默认值统一由 config_manager.DEFAULTS 提供）"""
    from backend.config_manager import get_setting, DEFAULTS
    url = get_setting("feishu_webhook")
    return url if url else DEFAULTS.get("feishu_webhook", "")


def send_text(text: str) -> bool:
    """
    发送纯文本消息到飞书群。

    Returns:
        True 成功，False 失败
    """
    from backend.config_manager import get_setting

    enabled = get_setting("feishu_enabled")
    if enabled != "true":
        logger.info("Feishu notification disabled, skip")
        return False

    webhook = _get_webhook_url()
    if not webhook:
        logger.warning("Feishu webhook not configured")
        return False

    payload = {
        "msg_type": "text",
        "content": {
            "text": text
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, headers={
        "Content-Type": "application/json; charset=utf-8"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                logger.info("Feishu notification sent successfully")
                return True
            else:
                logger.error(f"Feishu notification failed: {result}")
                return False
    except Exception as e:
        logger.error(f"Feishu notification request failed: {e}")
        return False


def send_card(title: str, elements: list) -> bool:
    """
    发送交互式卡片消息到飞书群。

    Args:
        title: 卡片标题
        elements: 卡片元素列表（飞书卡片 JSON 格式）

    Returns:
        True 成功，False 失败
    """
    from backend.config_manager import get_setting

    enabled = get_setting("feishu_enabled")
    if enabled != "true":
        return False

    webhook = _get_webhook_url()
    if not webhook:
        return False

    header_color = "blue"

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": header_color
            },
            "elements": elements
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, headers={
        "Content-Type": "application/json; charset=utf-8"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("code") == 0
    except Exception as e:
        logger.error(f"Feishu card notification failed: {e}")
        # 降级为纯文本
        fallback = f"{title}\n\n" + "\n".join(
            e.get("tag", "") for e in elements if isinstance(e, dict)
        )
        return send_text(fallback)


def notify_single_done():
    """单视频解析完成通知"""
    return send_text("老板，视频转写好了")


def notify_batch_done():
    """批量解析完成通知"""
    return send_text("老板，视频转写好了")


def send_transcript_text(text_content: str) -> bool:
    """
    发送转写结果文本到飞书。超长自动截断。

    Args:
        text_content: 转写文本内容

    Returns:
        True 成功，False 失败
    """
    if not text_content or not text_content.strip():
        return False

    max_len = 15000
    if len(text_content) > max_len:
        text_content = text_content[:max_len] + "…（内容过长已截断）"

    return send_text(text_content)


def test_webhook(webhook_url: str) -> tuple:
    """
    测试 webhook 是否可用。

    Returns:
        (success: bool, message: str)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "msg_type": "text",
        "content": {
            "text": "老板，视频转写好了"
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                return True, "发送成功，请检查飞书群消息"
            else:
                return False, f"飞书返回错误: code={result.get('code')}, msg={result.get('msg', '未知')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP 错误: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, f"网络错误: {e.reason}"
    except Exception as e:
        return False, f"发送失败: {e}"

