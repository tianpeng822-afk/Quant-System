import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, Enum, ForeignKey,
    Index, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PendingOrderStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class PendingOrder(Base):
    """
    待确认定投订单 (Pending SIP Orders)
    用于保存用户提交的、尚未确认净值的盲跑买入订单。
    ETL 系统在净值发布后自动折算份额并转化为正式 Transaction。
    """
    __tablename__ = "pending_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    fund_code: Mapped[str] = mapped_column(String(12), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(64), nullable=False)
    
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, comment="总扣款金额")
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.15"), comment="手续费率（%）")
    
    status: Mapped[PendingOrderStatus] = mapped_column(
        Enum(PendingOrderStatus), nullable=False, default=PendingOrderStatus.PENDING
    )
    
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", foreign_keys=[account_id]
    )

    __table_args__ = (
        Index("ix_pending_trade_date_status", "trade_date", "status"),
    )

    def __repr__(self) -> str:
        return f"<PendingOrder {self.id} fund={self.fund_code} amount={self.amount} status={self.status.value}>"
