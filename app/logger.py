"""
日志配置
统一初始化 loguru，输出到控制台 + 按天滚动的日志文件
"""

import sys
from pathlib import Path

from loguru import logger

from app.config import settings


def setup_logger() -> None:
    """配置全局日志，应在程序启动时调用一次"""
    log_dir: Path = settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # 移除 loguru 默认 handler
    logger.remove()

    # 控制台输出（彩色）
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # 文件输出（按天滚动，保留 30 天）
    logger.add(
        log_dir / "myfund_{time:YYYY-MM-DD}.log",
        level=settings.LOG_LEVEL,
        rotation="00:00",       # 每天午夜滚动
        retention="30 days",    # 保留最近 30 天
        encoding="utf-8",
        enqueue=True,           # 异步写入，避免阻塞
    )

    logger.info("Logger initialized. Level={}", settings.LOG_LEVEL)
