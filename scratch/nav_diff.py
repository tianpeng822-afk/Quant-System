import sys, os, json
sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import Holding, DailySnapshot, NavHistory

db = SessionLocal()
holdings = db.query(Holding).filter(Holding.shares > 0).all()

import datetime
today = datetime.datetime.now().date()
baseline_snap = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date < today).order_by(DailySnapshot.snapshot_date.desc()).first()

print(f"--- 真实净值变动 (基于当前份额 * (今日净值 - 昨日净值)) ---")
total_diff = 0
for h in holdings:
    code = h.fund_code
    live_nav = float(h.latest_nav or 0)
    
    # 获取昨日净值 (可以通过 snap，也可以查 NavHistory)
    yesterday_nav = None
    if baseline_snap and baseline_snap.holdings_snapshot:
        for item in json.loads(baseline_snap.holdings_snapshot):
            if item["fund_code"] == code:
                # Calculate nav from mv and shares
                mv = float(item["market_value"])
                shares = float(item["shares"])
                if shares > 0:
                    yesterday_nav = mv / shares
                break
                
    if yesterday_nav is None:
        continue
        
    nav_diff = live_nav - yesterday_nav
    pnl_diff = nav_diff * float(h.shares)
    total_diff += pnl_diff
    print(f"[{code}] {h.fund_name[:10]}:")
    print(f"   昨日净值: {yesterday_nav:.4f} -> 今日净值: {live_nav:.4f} (变化: {nav_diff:.4f})")
    print(f"   持有份额: {float(h.shares):.4f} => 产生盈亏: {pnl_diff:.2f}")

print(f"------------------------------------------------")
print(f"真实总变动 (估算): {total_diff:.2f}")
