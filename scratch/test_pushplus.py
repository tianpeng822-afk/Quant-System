import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.notifier.pushplus import send_wechat
success = send_wechat("Test from MyFund", "This is a test message to verify PushPlus works.")
print("PushPlus success:", success)
