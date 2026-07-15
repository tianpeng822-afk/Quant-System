"""
净值历史表 (nav_history)
────────────────────────────────────────────────
功能：存储每只基金每个交易日的净值数据（由 AkShare 抓取）。
作为时序数据源，供盈亏计算、回撤追踪、历史对比使用。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NavHistory(Base):
    """
    净值历史表

    Columns
    -------
    fund_code       : 基金代码
    fund_name       : 基金名称（冗余）
    nav_date        : 净值日期（交易日）
    unit_nav        : 单位净值（元/份）
    accum_nav       : 累计净值（含分红，元/份）
    daily_return    : 日涨跌幅（%，如 1.23 表示涨 1.23%）
    source          : 数据来源（AkShare / 手动）
    fetched_at      : 数据抓取时间（UTC）
    """

    __tablename__ = "nav_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    fund_code: Mapped[str] = mapped_column(
        String(12), nullable=False, comment="基金代码"
    )
    fund_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="基金名称（冗余）"
    )
    nav_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="净值日期"
    )
    unit_nav: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, comment="单位净值（元/份）"
    )
    accum_nav: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="累计净值（含分红，元/份）"
    )
    daily_return: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="日涨跌幅（%）"
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AkShare", comment="数据来源"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="抓取时间（UTC）",
    )

    __table_args__ = (
        # 同一只基金同一天只能有一条净值记录
        UniqueConstraint("fund_code", "nav_date", name="uq_nav_fund_date"),
        Index("ix_nav_fund_code", "fund_code"),
        Index("ix_nav_date", "nav_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<NavHistory fund={self.fund_code} date={self.nav_date} "
            f"nav={self.unit_nav}>"
        )
