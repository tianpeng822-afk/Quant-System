import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import Holding

db = get_db_session()
# 修复 163406
h = db.query(Holding).filter_by(fund_code="163406").first()
if h:
    print(f"Old peak: {h.peak_pnl_pct}, current: {h.unrealized_pnl_pct}")
    h.peak_pnl_pct = h.unrealized_pnl_pct
    db.commit()
    print("Fixed 163406.")

# 也顺便检查其它可能因为bug导致的历史遗留高得离谱的 peak_pnl_pct
for other in db.query(Holding).all():
    if other.peak_pnl_pct and other.unrealized_pnl_pct and other.peak_pnl_pct > other.unrealized_pnl_pct * 2 and other.peak_pnl_pct > 50:
        print(f"Fixing {other.fund_code}: peak {other.peak_pnl_pct} -> {other.unrealized_pnl_pct}")
        other.peak_pnl_pct = other.unrealized_pnl_pct
        db.commit()

db.close()
