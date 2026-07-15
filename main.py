"""
程序主入口
────────────────────────────────────────────────
支持两种运行模式：
  1. python main.py          → 启动 APScheduler 守护进程（每天 22:30 触发 ETL）
  2. python main.py --now    → 立即执行一次 ETL（调试/手动触发用）
"""

import argparse
import sys

from loguru import logger

from app.logger import setup_logger
from app.database import init_db
from app.pipeline import run_daily_etl
from app.config import settings


def main() -> None:
    setup_logger()
    init_db()

    parser = argparse.ArgumentParser(description="MyFund-Quant-System")
    parser.add_argument(
        "--now", action="store_true", help="立即执行一次 ETL（不启动调度器）"
    )
    args = parser.parse_args()

    if args.now:
        logger.info("手动触发模式：立即执行 ETL")
        run_daily_etl()
        return

    # ── 启动 APScheduler 定时任务 ────────────────────────────
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        func=run_daily_etl,
        trigger=CronTrigger(
            hour=settings.ETL_HOUR,
            minute=settings.ETL_MINUTE,
            timezone="Asia/Shanghai",
        ),
        id="daily_etl",
        name="每日 ETL 任务",
        replace_existing=True,
        misfire_grace_time=600,  # 允许 10 分钟内的触发误差
    )

    logger.info(
        "调度器启动，ETL 将在每天 {:02d}:{:02d} (Asia/Shanghai) 触发",
        settings.ETL_HOUR,
        settings.ETL_MINUTE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")
        sys.exit(0)


if __name__ == "__main__":
    main()
