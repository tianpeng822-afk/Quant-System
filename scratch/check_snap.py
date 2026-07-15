import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import DailySnapshot

db = get_db_session()
snaps = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(5).all()
for s in snaps:
    print(f"{s.snapshot_date}: PnL = {s.total_unrealized_pnl}")
