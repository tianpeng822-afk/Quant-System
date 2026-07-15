import sys
from pathlib import Path
from decimal import Decimal
import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import Holding, DailySnapshot
from app.pipeline import _build_report

db = get_db_session()
holdings = db.query(Holding).filter(Holding.shares > 0).all()
total_cost = sum(h.total_cost or Decimal("0") for h in holdings)
total_mv = sum(h.market_value or Decimal("0") for h in holdings)
total_unrealized = sum(h.unrealized_pnl or Decimal("0") for h in holdings)
total_pnl_pct = (total_unrealized / total_cost * 100).quantize(Decimal("0.0001")) if total_cost else Decimal("0")

# mock parameters to trigger the text
for h in holdings:
    if h.fund_code == '008903':
        h.trailing_stop_start_pct = Decimal("30.0")
        h.trailing_stop_tolerance_pct = Decimal("8.0")
    if h.fund_code == '004674':
        h.target_stop_loss = Decimal("-10.0")
    if h.fund_code == '019034':
        h.target_stop_profit = Decimal("15.0")

daily_pnl = Decimal("350.50") # Mock positive pnl

report = _build_report(datetime.date.today(), holdings, total_mv, total_unrealized, total_pnl_pct, daily_pnl)
print(report)
