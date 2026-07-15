"""
电子邮件 (SMTP) 推送适配器
────────────────────────────────────────────────
通过 SMTP 协议发送邮件通知，支持 Markdown 转换为精美的 HTML 发送。
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from loguru import logger
import markdown

from app.config import settings

def _markdown_to_html(md_text: str) -> str:
    """使用 markdown 库将 md 文本转换为带表格样式的 HTML"""
    # 使用 markdown 库转换，并开启 tables 扩展
    html = markdown.markdown(md_text, extensions=['tables'])
    
    # 添加一些 CSS 样式让表格看起来舒服点
    style = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; padding: 10px; }
        h2 { color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        h3 { color: #34495e; }
        table { border-collapse: collapse; width: 100%; max-width: 600px; margin: 10px 0; font-size: 14px; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background-color: #f8f9fa; color: #333; font-weight: 600; }
        tr:nth-child(even) { background-color: #f9f9f9; }
    </style>
    """
    return f"<!DOCTYPE html><html><head>{style}</head><body>{html}</body></html>"


def send_email(title: str, content: str) -> bool:
    """
    通过 SMTP 发送邮件。

    Parameters
    ----------
    title   : 邮件标题
    content : 邮件正文（Markdown 格式）
    """
    if not settings.SMTP_SERVER or not settings.SMTP_USER or not settings.SMTP_PASSWORD or not settings.SMTP_RECEIVER:
        logger.warning("SMTP 参数配置不完整，跳过邮件推送")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.SMTP_RECEIVER

    # 附加纯文本和 HTML
    part1 = MIMEText(content, "plain", "utf-8")
    part2 = MIMEText(_markdown_to_html(content), "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)

    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=15)
            server.starttls()
            
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_USER, settings.SMTP_RECEIVER, msg.as_string())
        server.quit()
        logger.info("📧 邮件推送成功！")
        return True
    except Exception as exc:
        logger.error("📧 邮件推送异常：{}", exc)
        return False
