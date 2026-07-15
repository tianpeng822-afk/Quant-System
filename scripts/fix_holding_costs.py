import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import Holding
from app.engine.recalc import recalculate_holding_costs

def fix_all():
    db = SessionLocal()
    try:
        holdings = db.query(Holding).all()
        for h in holdings:
            recalculate_holding_costs(db, h)
        db.commit()
        print(f"Successfully recalculated {len(holdings)} holdings.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_all()
