"""
ORM 基类：所有 Model 均继承此 Base，
统一注册 metadata，方便 create_all / alembic 迁移
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
