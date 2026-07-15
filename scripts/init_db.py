"""
数据库初始化脚本（首次部署时运行）
用于手动建表、插入测试账户数据
运行方式：python scripts/init_db.py
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from app.logger import setup_logger
from app.database import init_db, SessionLocal
from app.models import Account, AccountType


def seed_demo_data() -> None:
    """插入演示账户（首次运行用，可按需修改）"""
    db = SessionLocal()
    try:
        # 检查是否已有数据，避免重复插入
        if db.query(Account).count() > 0:
            logger.info("账户数据已存在，跳过 seed")
            return

        demo_accounts = [
            Account(
                name="本人-支付宝",
                account_type=AccountType.PERSONAL,
                owner="本人",
                platform="支付宝",
                currency="CNY",
                description="支付宝基金账户，主力定投账户",
            ),
            Account(
                name="本人-天天基金",
                account_type=AccountType.PERSONAL,
                owner="本人",
                platform="天天基金",
                currency="CNY",
                description="天天基金账户，主投主动权益类",
            ),
            Account(
                name="配偶-支付宝",
                account_type=AccountType.FAMILY,
                owner="配偶",
                platform="支付宝",
                currency="CNY",
                description="家庭成员账户",
            ),
        ]

        db.add_all(demo_accounts)
        db.commit()
        logger.success("演示账户 seed 完成，共插入 {} 条", len(demo_accounts))

    except Exception as exc:
        db.rollback()
        logger.exception("seed 数据失败：{}", exc)
    finally:
        db.close()


if __name__ == "__main__":
    setup_logger()
    logger.info("开始初始化数据库...")
    init_db()
    seed_demo_data()
    logger.success("✅ 数据库初始化完成！数据文件：data/myfund.db")
