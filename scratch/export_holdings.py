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
        "持有份额": float(h.shares),
        "成本均价": float(h.avg_cost_price) if h.avg_cost_price else 0,
        "总成本": float(h.total_cost) if h.total_cost else 0,
        "当前市值": float(h.market_value) if h.market_value else 0,
        "浮动盈亏": float(h.unrealized_pnl) if h.unrealized_pnl else 0,
        "盈亏率(%)": float(h.unrealized_pnl_pct) if h.unrealized_pnl_pct else 0,
        "最新净值": float(h.latest_nav) if h.latest_nav else 0,
        "净值日期": str(h.latest_nav_date)
    })

print(json.dumps(res, ensure_ascii=False, indent=2))
