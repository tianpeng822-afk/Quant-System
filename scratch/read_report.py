import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import DailySnapshot
from datetime import date

db = get_db_session()
today = date.today()
snap = db.query(DailySnapshot).filter_by(snapshot_date=today).first()
if snap and snap.report_content:
    print(snap.report_content)
else:
    print("No report found for today.")
