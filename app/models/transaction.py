"""
流水表 (transactions)
────────────────────────────────────────────────
功能：记录每一笔资金操作的原始流水，是系统数据的"唯一真相来源"。
所有的成本、份额、盈亏均由此表计算得出。
"""

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, Enum, ForeignKey,
    Index, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TransactionType(str, enum.Enum):
    """流水类型枚举"""
    BUY             = "buy"              # 申购（普通买入）
    SELL            = "sell"             # 赎回（卖出）
    DIVIDEND_CASH   = "dividend_cash"    # 分红派现（现金到账）
    DIVIDEND_REINVEST = "dividend_reinvest"  # 红利再投（转为份额）
    TRANSFER_IN     = "transfer_in"      # 转入（账户间调仓）
    TRANSFER_OUT    = "transfer_out"     # 转出（账户间调仓）


class TransactionStatus(str, enum.Enum):
    """流水状态枚举"""
    PENDING = "pending"                  # 待确认（盲买，未出净值）
    CONFIRMED = "confirmed"              # 已确认（净值已出，份额已计算）


class Transaction(Base):
    """
    流水表

    Columns（核心字段说明）
    ----------------------
    account_id      : 关联账户（外键）
    holding_id      : 关联持仓（外键，可空——赎回后持仓可能清零删除时的兜底）
    fund_code       : 基金代码（冗余，方便单表查询）
    fund_name       : 基金名称（冗余）
    tx_type         : 流水类型枚举
    trade_date      : 交易日期（申购/赎回确认日）
    confirm_date    : 份额到账日（T+1 或 T+2，用于精确 XIRR）
    shares          : 变动份额（买入为正，卖出为负）
    nav_price       : 成交净值（元/份）
    amount          : 交易金额（买入时含手续费的实际扣款，赎回时为实际到账金额）
    fee             : 手续费（元）
    net_amount      : 净交易金额 = amount - fee（买入时的纯本金部分）
    realized_pnl    : 已实现盈亏（仅赎回/分红类型有值，元）
    source          : 数据来源标记，如"手动录入"、"AkShare自动同步"
    external_id     : 外部系统流水号（去重用，如平台订单号）
    memo            : 备注
    created_at      : 记录写入时间（UTC）
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 关联 ──────────────────────────────────────────────────
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账户ID",
    )
    holding_id: Mapped[int | None] = mapped_column(
        ForeignKey("holdings.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联持仓ID（可空）",
    )

    # ── 基金标识（冗余）──────────────────────────────────────
    fund_code: Mapped[str] = mapped_column(
        String(12), nullable=False, comment="基金代码"
    )
    fund_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="基金名称（冗余）"
    )

    # ── 交易核心字段 ──────────────────────────────────────────
    tx_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False, comment="流水类型"
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), nullable=False, default=TransactionStatus.CONFIRMED,
        comment="流水状态：pending-待确认（盲买），confirmed-已确认"
    )
    trade_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="交易日期（申请日）"
    )
    confirm_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="份额确认日（到账日）"
    )
    shares: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True,
        comment="变动份额（买入正，卖出负），盲买时为空"
    )
    nav_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="成交净值（元/份），盲买时为空"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False,
        comment="交易总金额（买入含手续费实扣，赎回为到账金额，元）",
    )
    fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, default=Decimal("0.0000"),
        comment="手续费（元），盲买时为空"
    )
    net_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True,
        comment="净金额 = amount - fee（买入时纯本金，元），盲买时为空"
    )

    # ── 盈亏（赎回时计算）────────────────────────────────────
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True,
        comment="已实现盈亏（仅赎回/分红有值，元）",
    )

    # ── 元数据 ────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="手动录入",
        comment="数据来源，如：手动录入 / AkShare自动同步",
    )
    external_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True,
        comment="外部流水号（平台订单号，用于去重）",
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── 关联关系 ──────────────────────────────────────────────
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="transactions"
    )
    holding: Mapped["Holding | None"] = relationship(  # noqa: F821
        "Holding", back_populates="transactions"
    )

    # ── 索引 ──────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tx_account_id", "account_id"),
        Index("ix_tx_fund_code", "fund_code"),
        Index("ix_tx_trade_date", "trade_date"),
        Index("ix_tx_type", "tx_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} type={self.tx_type.value} "
            f"fund={self.fund_code} date={self.trade_date} amount={self.amount}>"
        )
