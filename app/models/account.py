"""
账户表 (accounts)
────────────────────────────────────────────────
功能：支持多账户隔离管理（个人、家人、联名等）
每笔流水、每条持仓都归属于某一个 account_id
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

import enum


class AccountType(str, enum.Enum):
    """账户类型"""
    PERSONAL  = "personal"   # 个人账户
    FAMILY    = "family"     # 家庭成员账户
    JOINT     = "joint"      # 联名账户


class Account(Base):
    """
    账户表

    Columns
    -------
    id          : 主键（自增整数）
    name        : 账户显示名称，如"本人-支付宝"、"配偶-天天基金"
    account_type: 账户类型枚举
    owner       : 持有人姓名（真实姓名，用于报告区分）
    platform    : 开户平台，如"支付宝"、"天天基金"、"雪球"
    currency    : 计价货币，默认 CNY
    is_active   : 是否启用（软删除标记）
    description : 备注说明
    created_at  : 记录创建时间（UTC）
    updated_at  : 记录最后更新时间（UTC）
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="账户显示名称"
    )
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType), nullable=False, default=AccountType.PERSONAL, comment="账户类型"
    )
    owner: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="持有人姓名"
    )
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="天天基金", comment="开户平台"
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="CNY", comment="计价货币"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="备注说明"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间(UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="更新时间(UTC)",
    )

    # ── 反向关联 ──────────────────────────────────────────────
    holdings: Mapped[list["Holding"]] = relationship(  # noqa: F821
        "Holding", back_populates="account", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} owner={self.owner!r}>"
