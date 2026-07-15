import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import run_daily_etl
run_daily_etl()
