import sys, os
sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import NavHistory
db = SessionLocal()
navs = db.query(NavHistory).filter(NavHistory.nav_date >= '2026-07-08').order_by(NavHistory.fund_code, NavHistory.nav_date).all()
for n in navs:
    print(f"{n.fund_code} | {n.nav_date} | {n.unit_nav}")
