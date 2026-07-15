# web/utils.py
# 共享工具函数：路径修正、数据库连接、通用格式化

import sys
from pathlib import Path

# 确保项目根目录在 sys.path，无论从哪里运行 streamlit
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402


def get_db_session():
    """返回一个 SQLAlchemy Session，调用方负责关闭"""
    return SessionLocal()


def fmt_money(value, prefix="¥") -> str:
    """格式化金额显示"""
    if value is None:
        return "N/A"
    try:
        v = float(value)
        sign = "+" if v > 0 else ""
        return f"{prefix}{sign}{v:,.2f}" if v != 0 else f"{prefix}0.00"
    except Exception:
        return str(value)


def fmt_pct(value) -> str:
    """格式化百分比显示"""
    if value is None:
        return "N/A"
    try:
        v = float(value)
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.2f}%"
    except Exception:
        return str(value)


def pnl_color(value) -> str:
    """根据正负值返回颜色 (A股：红涨绿跌)"""
    try:
        return "#FF4B4B" if float(value) >= 0 else "#00D4AA"
    except Exception:
        return "#888888"
