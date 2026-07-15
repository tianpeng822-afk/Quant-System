import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import Holding
import json

db = get_db_session()
holdings = db.query(Holding).filter(Holding.shares > 0).all()

res = []
for h in holdings:
    res.append({
        "基金名称": h.fund_name,
        "基金代码": h.fund_code,
        "浮动盈亏": float(h.unrealized_pnl_pct) if h.unrealized_pnl_pct else 0,
        "目标止盈(%)": float(h.target_stop_profit) if h.target_stop_profit else None,
        "止损/抄底线(%)": float(h.target_stop_loss) if h.target_stop_loss else None,
        "移动止盈启动线(%)": float(h.trailing_stop_start_pct) if h.trailing_stop_start_pct else None,
        "移动止盈回撤容忍(%)": float(h.trailing_stop_tolerance_pct) if h.trailing_stop_tolerance_pct else None,
    })

print(json.dumps(res, ensure_ascii=False, indent=2))
