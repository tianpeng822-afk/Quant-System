"""
PushPlus 微信推送适配器（Phase 1）
────────────────────────────────────────────────
调用 PushPlus API 将消息推送到微信公众号。
文档参考：https://www.pushplus.plus/doc/
"""

import httpx
from loguru import logger

from app.config import settings

PUSHPLUS_API = "https://www.pushplus.plus/send"


def send_wechat(title: str, content: str, template: str = "markdown") -> bool:
    """
    通过 PushPlus 发送微信消息。

    Parameters
    ----------
    title    : 消息标题
    content  : 消息正文（支持 Markdown）
    template : 模板类型，默认 markdown

    Returns
    -------
    True 表示发送成功，False 表示失败
    """
    if not settings.PUSHPLUS_TOKEN:
        logger.warning("PUSHPLUS_TOKEN 未配置，跳过微信推送")
        return False

    payload = {
        "token": settings.PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": template,
    }

    try:
        import subprocess
        import json
        payload_str = json.dumps(payload)
        cmd = [
            "curl", "-s", "-X", "POST",
            "https://www.pushplus.plus/send",
            "-H", "Content-Type: application/json",
            "-d", payload_str,
            "--ipv4", "-m", "15"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("code") == 200:
                logger.info("微信推送成功：{}", title)
                return True
            else:
                logger.error("微信推送失败，返回：{}", data)
                return False
        else:
            logger.error("微信推送 curl 失败: {}", result.stderr)
            return False
    except Exception as exc:
        logger.error("微信推送异常：{}", exc)
        return False
