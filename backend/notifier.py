"""
QQ邮箱通知模块：定期跟踪完成后发送提醒到手机（微信QQ邮箱提醒）
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging

logger = logging.getLogger("notifier")

# QQ邮箱 SMTP 固定配置
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465


def send_notification(subject: str, body: str) -> bool:
    """
    发送QQ邮件通知。

    前置条件：config 中已配置 email_auth_code 且 email_enabled 为 "true"。

    Returns:
        True 发送成功，False 失败
    """
    from backend.config_manager import get_setting

    enabled = get_setting("email_enabled")
    if enabled != "true":
        logger.info("Email notification disabled, skip")
        return False

    auth_code = get_setting("email_auth_code")
    if not auth_code:
        logger.warning("Email auth code not configured")
        return False

    sender = get_setting("email_sender")
    receiver = get_setting("email_receiver") or sender

    if not sender:
        logger.warning("Email sender not configured")
        return False

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(sender, auth_code)
            server.sendmail(sender, [receiver], msg.as_string())
        logger.info(f"Notification sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return False


def notify_batch_done(save_dir: str, success_count: int, total: int, batch_summary_path: str | None = None):
    """
    定期跟踪完成后的模板通知。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[股票工具] 定期跟踪完成 {now}"
    lines = [
        f"处理完成时间：{now}",
        f"成功转写：{success_count}/{total} 个视频",
        f"保存路径：{save_dir}",
    ]
    if batch_summary_path:
        lines.append(f"批次总结：{batch_summary_path}")
    else:
        lines.append("批次总结：未生成")

    body = "\n".join(lines)
    send_notification(subject, body)

