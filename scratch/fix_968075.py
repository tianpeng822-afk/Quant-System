import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.utils import get_db_session
from app.models import Holding, Transaction
from decimal import Decimal

db = get_db_session()

holding = db.query(Holding).filter(Holding.fund_code == "968075", Holding.account_id == 1).first()
print(f"Before: shares={holding.shares}, total_cost={holding.total_cost}, avg_cost={holding.avg_cost_price}")

# 买入总份额: 58.4 + 28.3389 + 28.72 = 115.4589
# 卖出份额: 115.42
# 剩余: 0.0389 份，成本极小 (约0.67元)
# 实际已清仓，把剩余份额和成本清零

holding.shares = Decimal('0')
holding.total_cost = Decimal('0')
holding.avg_cost_price = Decimal('0')

db.commit()
print(f"After: shares={holding.shares}, total_cost={holding.total_cost}, avg_cost={holding.avg_cost_price}")
print("✅ 968075 已清零完成")
