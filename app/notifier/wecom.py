"""
企业微信群机器人推送适配器
────────────────────────────────────────────────
调用企业微信 Webhook API 将消息推送到内部群。
文档参考：https://developer.work.weixin.qq.com/document/path/91770
"""

import httpx
from loguru import logger

from app.config import settings


def send_wecom(content: str, is_markdown: bool = True) -> bool:
    """
    通过企业微信机器人 Webhook 发送消息。

    Parameters
    ----------
    content     : 消息正文
    is_markdown : 是否使用 Markdown 格式（默认 True）

    Returns
    -------
    True 表示发送成功，False 表示失败
    """
    if not settings.WECOM_WEBHOOK_URL:
        logger.warning("WECOM_WEBHOOK_URL 未配置，跳过企业微信推送")
        return False

    msgtype = "markdown" if is_markdown else "text"
    payload = {
        "msgtype": msgtype,
        msgtype: {
            "content": content
        }
    }

    try:
        resp = httpx.post(settings.WECOM_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("企业微信推送成功！")
            return True
        else:
            logger.error("企业微信推送失败，返回：{}", data)
            return False
    except Exception as exc:
        logger.error("企业微信推送异常：{}", exc)
        return False
