import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from datetime import datetime
import os

df = pd.read_csv("data/163406_history_v2.csv")
df["净值日期"] = pd.to_datetime(df["净值日期"])
df["累计净值"] = df["累计净值"].astype(float)
df = df.sort_values(by="净值日期").reset_index(drop=True)
start_date_input = datetime.today().date() - pd.Timedelta(days=365*5)
df = df[(df["净值日期"].dt.date >= start_date_input)].reset_index(drop=True)
df['peak_nav'] = df["累计净值"].cummax()
df['fund_drawdown'] = (df["累计净值"] - df['peak_nav']) / df['peak_nav']

def run_backtest(start_pct):
    total_shares = 0.0
    total_cost = 0.0
    total_invested = 0.0
    cash_pool = 0.0
    last_invest_period = None
    peak_profit_pct = 0.0
    
    for idx, row in df.iterrows():
        current_date = row["净值日期"]
        current_nav = row["累计净值"]
        
        current_period = (current_date.year, current_date.month)
        if current_period != last_invest_period and current_date.day >= 1:
            actual_invest_amount = 1000.0
            buy_shares = actual_invest_amount / current_nav
            total_shares += buy_shares
            total_cost += actual_invest_amount
            total_invested += actual_invest_amount
            last_invest_period = current_period
            
        current_market_value = total_shares * current_nav
        profit_pct = 0.0
        if total_cost > 0:
            profit_pct = (current_market_value - total_cost) / total_cost
            trigger_sell = False
            
            if profit_pct > peak_profit_pct:
                peak_profit_pct = profit_pct
                
            if peak_profit_pct >= (start_pct / 100.0):
                if profit_pct <= peak_profit_pct - (8.0 / 100.0):
                    trigger_sell = True
            
            if trigger_sell:
                sell_shares = total_shares * (100.0 / 100.0)
                cash_out = sell_shares * current_nav
                cash_pool += cash_out
                total_shares -= sell_shares
                total_cost = total_shares * current_nav  
                current_market_value = total_shares * current_nav
                peak_profit_pct = 0.0

    return cash_pool + total_shares * df.iloc[-1]["累计净值"]

print("30%:", run_backtest(30.0))
print("15%:", run_backtest(15.0))
print("10%:", run_backtest(10.0))
