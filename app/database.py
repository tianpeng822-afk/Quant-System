"""
MyFund-Quant-System 数据库配置入口
负责创建引擎、Session 工厂，以及初始化所有表结构
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.models.base import Base

# 加载 .env 配置
load_dotenv()

# ── 数据库路径 ──────────────────────────────────────────────
_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/myfund.db")

# 确保 data/ 目录存在（SQLite 文件路径）
if _DATABASE_URL.startswith("sqlite:///"):
    _db_file = Path(_DATABASE_URL.replace("sqlite:///", ""))
    _db_file.parent.mkdir(parents=True, exist_ok=True)

# ── 引擎 & Session 工厂 ─────────────────────────────────────
engine = create_engine(
    _DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 多线程安全
    echo=False,  # 调试时可改为 True 打印 SQL
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def init_db() -> None:
    """创建所有表（首次运行 / 迁移兜底）"""
    # 显式导入所有 Model，确保 metadata 注册完整
    import app.models.account  # noqa: F401
    import app.models.holding  # noqa: F401
    import app.models.transaction  # noqa: F401
    import app.models.nav_history  # noqa: F401
    import app.models.daily_snapshot  # noqa: F401
    import app.models.pending_order  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized: {}", _DATABASE_URL)


def get_db():
    """FastAPI / 脚本通用的 Session 上下文管理器"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
