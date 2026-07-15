"""
每日快照表 (daily_snapshots)
────────────────────────────────────────────────
功能：每天 ETL 运行完毕后，把当天整个投资组合的汇总状态持久化保存。
作用相当于"日报存档"，用于绘制资产曲线、计算整体 XIRR。
一旦写入不再修改（append-only）。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailySnapshot(Base):
    """
    每日组合快照表

    Columns
    -------
    snapshot_date       : 快照日期（每天唯一）
    total_cost          : 累计投入总成本（所有账户合计，元）
    total_market_value  : 总市值（元）
    total_unrealized_pnl: 总浮动盈亏（元）
    total_realized_pnl  : 累计已实现盈亏（元）
    total_pnl           : 总盈亏 = 浮动 + 已实现（元）
    total_pnl_pct       : 总盈亏率（%）
    daily_pnl           : 今日单日盈亏（元，= 今日市值 - 昨日市值 + 今日赎回净流出）
    portfolio_xirr      : 投资组合年化收益率 XIRR（%，全量计算）
    benchmark_return    : 基准指数同期涨跌幅（%，如沪深300）
    excess_return       : 超额收益 = portfolio_xirr - benchmark_return（%）
    holdings_snapshot   : 当天各基金持仓状态 JSON 快照（用于离线审计）
    report_sent         : 当天推送消息是否已发送成功
    report_content      : 推送的完整文本内容存档
    created_at          : 快照写入时间（UTC）
    """

    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    snapshot_date: Mapped[date] = mapped_column(
        Date, nullable=False, unique=True, comment="快照日期（每天唯一）"
    )

    # ── 资产汇总 ──────────────────────────────────────────────
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="累计投入总成本（元）",
    )
    total_market_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="总市值（元）",
    )
    total_unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="总浮动盈亏（元）",
    )
    total_realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="累计已实现盈亏（元）",
    )
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="总盈亏（浮动 + 已实现，元）",
    )
    total_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="总盈亏率（%）"
    )
    daily_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="当日单日盈亏（元）"
    )

    # ── 收益率指标 ────────────────────────────────────────────
    portfolio_xirr: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="组合年化收益率 XIRR（%）"
    )
    benchmark_return: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="基准指数同期涨跌幅（%）"
    )
    excess_return: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="超额收益（%）"
    )

    # ── 快照详情（JSON 文本存储）──────────────────────────────
    holdings_snapshot: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="当天各基金持仓状态 JSON 快照（离线审计用）",
    )

    # ── 推送状态 ──────────────────────────────────────────────
    report_sent: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="推送消息是否已成功发送"
    )
    report_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="推送完整文本内容存档"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="快照写入时间（UTC）",
    )

    __table_args__ = (
        Index("ix_snapshot_date", "snapshot_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<DailySnapshot date={self.snapshot_date} "
            f"mv={self.total_market_value} pnl={self.total_pnl}>"
        )
