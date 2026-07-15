import sys
import os
sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import Holding, DailySnapshot
import json

db = SessionLocal()
holdings = db.query(Holding).filter(Holding.shares > 0).all()
snapshots = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.asc()).all()

total_pnl = sum(float(h.unrealized_pnl or 0) for h in holdings)
baseline_snap = next((s for s in reversed(snapshots) if str(s.snapshot_date) < "2026-07-10"), None)
snap_pnl = float(baseline_snap.total_unrealized_pnl or 0) if baseline_snap else 0

print(f"Total PnL (live): {total_pnl}")
print(f"Baseline Snap PnL ({baseline_snap.snapshot_date if baseline_snap else None}): {snap_pnl}")
print(f"Daily PnL: {total_pnl - snap_pnl}")

print("Holdings details:")
for h in holdings:
    print(f"{h.fund_code} - {h.fund_name} | shares: {h.shares} | nav: {h.latest_nav} ({h.latest_nav_date}) | PnL: {h.unrealized_pnl}")

if baseline_snap:
    snap_data = json.loads(baseline_snap.holdings_snapshot)
    print("\nSnap details:")
    for h in snap_data:
        print(f"{h['fund_code']} | nav: {h.get('latest_nav')} | PnL: {h.get('unrealized_pnl')}")

