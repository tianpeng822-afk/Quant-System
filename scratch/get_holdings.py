import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import Holding

db = SessionLocal()
holdings = db.query(Holding).filter(Holding.shares > 0).all()
for h in holdings:
    print(f"[{h.fund_code}] {h.fund_name} - 类别: {h.fund_category} - 份额: {h.shares} - 成本: {h.total_cost} - 市值: {h.market_value} - 盈亏率: {h.unrealized_pnl_pct}% - 回撤: {h.current_drawdown}%")

db.close()
