import sys, os
sys.path.insert(0, os.path.abspath("."))
import datetime
from decimal import Decimal
from app.database import SessionLocal
from app.models import Holding, NavHistory

db = SessionLocal()
holdings = db.query(Holding).filter(Holding.shares > 0).all()
today = datetime.date(2026, 7, 10)

total_cost          = sum(h.total_cost or Decimal("0") for h in holdings)
total_market_value  = sum(h.market_value or Decimal("0") for h in holdings)
total_unrealized    = sum(h.unrealized_pnl or Decimal("0") for h in holdings)
total_pnl_pct = (
    (total_unrealized / total_cost * 100).quantize(Decimal("0.0001"))
    if total_cost else Decimal("0")
)

daily_pnl = Decimal("0")
for h in holdings:
    navs = db.query(NavHistory).filter(NavHistory.fund_code == h.fund_code, NavHistory.nav_date <= today).order_by(NavHistory.nav_date.desc()).limit(2).all()
    if len(navs) == 2:
        curr_nav = navs[0].unit_nav
        prev_nav = navs[1].unit_nav
        daily_pnl += (curr_nav - prev_nav) * h.shares

from app.pipeline import _build_report
report = _build_report(today, holdings, total_market_value, total_unrealized, total_pnl_pct, daily_pnl)
print(report)
