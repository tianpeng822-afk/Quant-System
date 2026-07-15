"""
全局配置管理
统一从环境变量（.env）读取所有配置项，并暴露为类型安全的属性
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 自动向上查找 .env 文件（支持从子目录运行脚本）
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class Settings:
    # ── 数据库 ─────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/myfund.db")

    # ── DeepSeek AI ────────────────────────────────────────────
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # ── 消息推送 ────────────────────────────────────────────────
    PUSHPLUS_TOKEN: str = os.getenv("PUSHPLUS_TOKEN", "")
    WECOM_WEBHOOK_URL: str = os.getenv("WECOM_WEBHOOK_URL", "")
    FEISHU_WEBHOOK_URL: str = os.getenv("FEISHU_WEBHOOK_URL", "")
    DINGTALK_WEBHOOK_URL: str = os.getenv("DINGTALK_WEBHOOK_URL", "")
    
    # ── 邮件推送 (SMTP) ─────────────────────────────────────────
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_RECEIVER: str = os.getenv("SMTP_RECEIVER", "")

    # ── 大模型 AI 接口 ──────────────────────────────────────────
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

    # ── 调度时间（24h 制）──────────────────────────────────────
    ETL_HOUR: int = int(os.getenv("ETL_HOUR", "22"))
    ETL_MINUTE: int = int(os.getenv("ETL_MINUTE", "30"))

    # ── 日志 ────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = _ROOT / "logs"

    # ── 基准指数代码（AkShare 格式）────────────────────────────
    BENCHMARK_INDEX_CODE: str = os.getenv("BENCHMARK_INDEX_CODE", "000300")  # 沪深300


settings = Settings()
