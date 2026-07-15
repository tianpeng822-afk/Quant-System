"""
资产持仓表 (holdings)
────────────────────────────────────────────────
功能：记录每个账户当前持有的每只基金的实时状态。
每次净值更新后，由 ETL 脚本刷新此表的市值和盈亏字段。
成本价支持 FIFO 和摊薄均价两种模式。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Holding(Base):
    """
    资产持仓表

    Columns（核心字段说明）
    ----------------------
    account_id          : 关联账户（外键）
    fund_code           : 基金代码，如 "110022"（易方达消费行业）
    fund_name           : 基金名称（冗余存储，避免频繁 JOIN）
    fund_category       : 大类资产标签，如 "A股/消费"、"美股/科技"、"固收"
    shares              : 当前持有份额（精度到小数点后4位）
    avg_cost_price      : 摊薄均价成本（元/份）
    fifo_cost_price     : FIFO 成本（元/份，Phase 2 精算用）
    total_cost          : 累计买入总成本（含手续费，元）
    latest_nav          : 最新净值（元/份）
    latest_nav_date     : 最新净值对应日期
    market_value        : 当前市值 = shares × latest_nav（元）
    unrealized_pnl      : 浮动盈亏 = market_value - total_cost（元）
    unrealized_pnl_pct  : 浮动盈亏率（%）
    peak_nav            : 历史最高净值（用于回撤追踪）
    current_drawdown    : 当前回撤幅度 = (latest_nav - peak_nav) / peak_nav（%）
    target_stop_profit  : 止盈目标浮盈率阈值（%），如 20.0
    target_stop_loss    : 止损回撤幅度阈值（%），如 -15.0
    memo                : 备注，如"定投计划-月投1000"
    created_at / updated_at : 时间戳
    """

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 关联账户 ───────────────────────────────────────────────
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账户ID",
    )

    # ── 基金基本信息 ──────────────────────────────────────────
    fund_code: Mapped[str] = mapped_column(
        String(12), nullable=False, comment="基金代码（6位数字）"
    )
    fund_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="基金名称（冗余）"
    )
    fund_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="大类资产标签，如 A股/消费"
    )

    # ── 持仓成本 ──────────────────────────────────────────────
    shares: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0.0000"),
        comment="持有份额",
    )
    avg_cost_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0.0000"),
        comment="摊薄均价成本（元/份）",
    )
    fifo_cost_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="FIFO成本（元/份，Phase 2用）",
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
        comment="累计买入总成本（含手续费，元）",
    )

    # ── 市值与盈亏（每日 ETL 刷新）────────────────────────────
    latest_nav: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="最新净值（元/份）"
    )
    latest_nav_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="最新净值对应日期"
    )
    market_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="当前市值（元）"
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="浮动盈亏（元）"
    )
    unrealized_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="浮动盈亏率（%，如 15.23）"
    )

    # ── 回撤追踪 ──────────────────────────────────────────────
    peak_nav: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="历史最高净值（回撤基准）"
    )
    current_drawdown: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="当前回撤幅度（%，负值，如 -12.50）",
    )

    # ── 移动止盈与回撤追踪 ────────────────────────────────
    peak_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="历史最高浮盈率（%）"
    )

    # ── 风控阈值（个性化配置）────────────────────────────────
    target_stop_profit: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
        comment="静态止盈目标（%），如 20.00",
    )
    target_stop_loss: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
        comment="绝对止损阈值（%），如 -15.00",
    )
    benchmark_index: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="估值参考的基准指数名称（如：沪深300）",
    )
    trailing_stop_start_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
        comment="移动止盈启动线（%），如 10.00（利润超过10%才开启跟随）",
    )
    trailing_stop_tolerance_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
        comment="移动止盈回撤容忍度（%），如 5.00（从最高利润回落5%触发）",
    )

    # ── 定投计划 ──────────────────────────────────────────────
    dca_weekly_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="每周定投金额（元），NULL=不定投",
    )
    dca_day_of_week: Mapped[int] = mapped_column(
        nullable=False, default=3,
        comment="定投星期几（0=周一, 6=周日），默认周四",
    )
    dca_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.1500"),
        comment="定投申购手续费率（%），如 0.15，C类基金填 0",
    )
    dca_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False,
        comment="是否启用定投",
    )
    smart_dca_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False,
        comment="[已废弃] 旧版智能加倍开关，请使用 dynamic_dca_enabled",
    )
    dynamic_dca_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False,
        comment="支付宝涨跌幅定投：按盈亏率动态调整扣款率",
    )

    memo: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── 关联关系 ──────────────────────────────────────────────
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="holdings"
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="holding"
    )

    # ── 唯一约束：同一账户不能重复持有同一只基金 ───────────────
    __table_args__ = (
        UniqueConstraint("account_id", "fund_code", name="uq_account_fund"),
        Index("ix_holdings_fund_code", "fund_code"),
        Index("ix_holdings_account_id", "account_id"),
        {"sqlite_autoincrement": False},  # 显式声明，避免歧义
    )

    def __repr__(self) -> str:
        return (
            f"<Holding id={self.id} fund={self.fund_code} "
            f"shares={self.shares} mv={self.market_value}>"
        )
