import sys
import os
sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import Holding

db = SessionLocal()
for code in ['519772', '968075']:
    h = db.query(Holding).filter_by(fund_code=code).first()
    if h:
        print(f"{h.fund_code} shares: {h.shares}, PnL: {h.unrealized_pnl}, Cost: {h.total_cost}")
    else:
        print(f"{code} not found")
