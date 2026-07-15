import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import Holding, Transaction

db = get_db_session()

holdings = db.query(Holding).filter(Holding.fund_code == "968075").all()
print("=== Holding ===")
for h in holdings:
    print(f"  account_id={h.account_id}, shares={h.shares}, total_cost={h.total_cost}, avg_cost={h.avg_cost_price}")

txns = db.query(Transaction).filter(Transaction.fund_code == "968075").order_by(Transaction.trade_date).all()
print(f"\n=== Transactions ({len(txns)} records) ===")
for t in txns:
    print(vars(t))
