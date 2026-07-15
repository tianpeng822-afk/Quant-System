import sys, os, json
sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import Holding, DailySnapshot, Transaction

db = SessionLocal()
holdings = db.query(Holding).filter(Holding.shares > 0).all()
snapshots = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).all()

# Find the baseline snap (last one before today)
import datetime
today = datetime.datetime.now().date()
baseline_snap = next((s for s in snapshots if s.snapshot_date < today), None)

snap_data = {}
if baseline_snap:
    for item in json.loads(baseline_snap.holdings_snapshot or "[]"):
        snap_data[item["fund_code"]] = item

print(f"--- Breakdown compared to snapshot on {baseline_snap.snapshot_date if baseline_snap else 'None'} ---")
total_diff = 0
for h in holdings:
    code = h.fund_code
    live_pnl = float(h.unrealized_pnl or 0)
    if code in snap_data:
        snap_pnl = float(snap_data[code].get("unrealized_pnl") or 0)
        snap_shares = float(snap_data[code].get("shares") or 0)
        diff = live_pnl - snap_pnl
        total_diff += diff
        print(f"[{code}] {h.fund_name[:10]}:")
        print(f"   昨日份额: {snap_shares} -> 今日份额: {h.shares}")
        print(f"   昨日浮盈: {snap_pnl} -> 今日浮盈: {live_pnl}")
        print(f"   => 本基金盈亏变化: {diff:.2f}")
    else:
        print(f"[{code}] {h.fund_name[:10]}: newly added, PnL {live_pnl}")
        total_diff += live_pnl

print(f"------------------------------------------------")
print(f"净值总变动(剔除已清仓): {total_diff:.2f}")

# Check transactions today
txs = db.query(Transaction).filter(Transaction.trade_date >= baseline_snap.snapshot_date).all()
print("\n--- 近期交易流水 (从昨日快照日期起) ---")
for tx in txs:
    print(f"日期: {tx.trade_date}, 基金: {tx.fund_code}, 操作: {tx.tx_type.value}, 份额: {tx.shares}, 金额: {tx.amount}")

