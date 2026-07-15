from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import Holding, Transaction
from app.models.transaction import TransactionType
import logging

logger = logging.getLogger(__name__)

def recalculate_holding_costs(db: Session, holding: Holding):
    """
    Recalculate shares, total_cost, and avg_cost_price for a holding
    based on all its transactions.
    """
    txs = db.query(Transaction).filter_by(holding_id=holding.id).order_by(
        Transaction.trade_date.asc(), Transaction.id.asc()
    ).all()
    
    shares = Decimal("0")
    total_cost = Decimal("0")
    avg_cost_price = Decimal("0")
    
    for tx in txs:
        if tx.tx_type in (TransactionType.BUY, TransactionType.TRANSFER_IN, TransactionType.DIVIDEND_REINVEST):
            shares += tx.shares
            total_cost += tx.amount # amount includes fee for BUY
            if shares > 0:
                avg_cost_price = (total_cost / shares).quantize(Decimal("0.0001"))
        elif tx.tx_type in (TransactionType.SELL, TransactionType.TRANSFER_OUT):
            # tx.shares is negative
            if shares > 0:
                # Deduct cost proportionally to the shares being sold
                sold_cost = (abs(tx.shares) / shares) * total_cost
                total_cost -= sold_cost
            shares += tx.shares
            if shares <= Decimal("0.0001"):
                shares = Decimal("0")
                total_cost = Decimal("0")
                avg_cost_price = Decimal("0")
        elif tx.tx_type == TransactionType.DIVIDEND_CASH:
            # Cash dividend reduces the total cost basis
            total_cost -= tx.amount
            if shares > 0:
                avg_cost_price = (total_cost / shares).quantize(Decimal("0.0001"))
            
    holding.shares = shares
    holding.total_cost = total_cost
    holding.avg_cost_price = avg_cost_price
    
    # Recalculate unrealized PnL based on the latest NAV
    if holding.latest_nav and holding.latest_nav > 0:
        holding.market_value = (holding.shares * holding.latest_nav).quantize(Decimal("0.01"))
        holding.unrealized_pnl = holding.market_value - holding.total_cost
        if holding.total_cost and holding.total_cost > 0:
            holding.unrealized_pnl_pct = (holding.unrealized_pnl / holding.total_cost * 100).quantize(Decimal("0.0001"))
        else:
            holding.unrealized_pnl_pct = Decimal("0")
    else:
        holding.market_value = Decimal("0")
        holding.unrealized_pnl = Decimal("0")
        holding.unrealized_pnl_pct = Decimal("0")
        
    db.add(holding)
