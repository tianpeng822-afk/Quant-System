"""
手动录入流水脚本（Phase 1 辅助工具）
用于快速录入历史申购/赎回记录，无需 GUI。
运行方式：python scripts/add_transaction.py
"""

import sys
from decimal import Decimal
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from app.logger import setup_logger
from app.database import SessionLocal
from app.models import Account, Holding, Transaction, TransactionType


def add_buy(
    account_name: str,
    fund_code: str,
    fund_name: str,
    trade_date: date,
    shares: Decimal,
    nav_price: Decimal,
    fee: Decimal = Decimal("0"),
    memo: str = "",
) -> None:
    """
    录入一笔申购流水，并同步更新或创建对应的 holdings 记录。

    Parameters
    ----------
    account_name : 账户名称（如"本人-支付宝"）
    fund_code    : 基金代码
    fund_name    : 基金名称
    trade_date   : 交易日期
    shares       : 申购份额
    nav_price    : 成交净值
    fee          : 手续费（元）
    memo         : 备注
    """
    db = SessionLocal()
    try:
        # 查找账户
        account = db.query(Account).filter_by(name=account_name).first()
        if not account:
            logger.error("账户不存在：{}", account_name)
            return

        gross_amount = (shares * nav_price + fee).quantize(Decimal("0.01"))
        net_amount   = (shares * nav_price).quantize(Decimal("0.01"))

        # 查找或创建持仓
        holding = (
            db.query(Holding)
            .filter_by(account_id=account.id, fund_code=fund_code)
            .first()
        )
        if holding is None:
            holding = Holding(
                account_id=account.id,
                fund_code=fund_code,
                fund_name=fund_name,
                shares=Decimal("0"),
                avg_cost_price=Decimal("0"),
                total_cost=Decimal("0"),
            )
            db.add(holding)
            db.flush()

        # 更新持仓：摊薄均价
        old_cost  = holding.total_cost
        old_shares = holding.shares
        new_shares = old_shares + shares
        new_cost   = old_cost + net_amount

        holding.shares         = new_shares
        holding.total_cost     = new_cost + fee   # 含手续费计入成本
        holding.avg_cost_price = (
            (new_cost + fee) / new_shares
        ).quantize(Decimal("0.0001"))

        # 插入流水
        tx = Transaction(
            account_id=account.id,
            holding_id=holding.id,
            fund_code=fund_code,
            fund_name=fund_name,
            tx_type=TransactionType.BUY,
            trade_date=trade_date,
            shares=shares,
            nav_price=nav_price,
            amount=gross_amount,
            fee=fee,
            net_amount=net_amount,
            source="手动录入",
            memo=memo,
        )
        db.add(tx)
        db.commit()
        logger.success(
            "申购流水录入成功 {} {} {} 份 净值={} 费用={}",
            account_name, fund_code, shares, nav_price, fee,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("录入失败：{}", exc)
    finally:
        db.close()


# ── 使用示例（取消注释后运行）────────────────────────────────
if __name__ == "__main__":
    setup_logger()

    # 示例：录入一笔易方达消费行业的申购记录
    add_buy(
        account_name="本人-支付宝",
        fund_code="110022",
        fund_name="易方达消费行业股票",
        trade_date=date(2024, 1, 15),
        shares=Decimal("1000.0000"),
        nav_price=Decimal("2.3500"),
        fee=Decimal("2.35"),
        memo="首次定投",
    )
