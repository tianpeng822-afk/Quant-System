import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Mock streamlit
class DummyST:
    def __init__(self):
        self.session_state = {'run_backtest_triggered': True}
    def warning(self, msg): print("WARNING:", msg)
    def stop(self): sys.exit(0)
    def info(self, msg): print("INFO:", msg)
    def error(self, msg): print("ERROR:", msg)
    def success(self, msg): print("SUCCESS:", msg)
    def progress(self, val): return DummyProgress()
    def subheader(self, msg): pass
    def caption(self, msg): pass
    def write(self, msg=""): pass
    def divider(self): pass
    def columns(self, n): return [DummyCol() for _ in range(n)]
    def plotly_chart(self, fig, **kwargs): pass
    def dataframe(self, df, **kwargs): pass
class DummyProgress:
    def progress(self, val): pass
    def empty(self): pass
class DummyCol:
    def metric(self, label, value, delta=None, help=None): pass

class DummySpinner:
    def __init__(self, msg): pass
    def __enter__(self): pass
    def __exit__(self, exc_type, exc_val, exc_tb): pass

import streamlit as st
st.session_state = {'run_backtest_triggered': True}
st.spinner = DummySpinner
st.warning = lambda msg: print("WARNING", msg)
st.stop = lambda: sys.exit(0)
st.info = lambda msg: print("INFO", msg)
st.error = lambda msg: print("ERROR", msg)
st.success = lambda msg: print("SUCCESS", msg)
st.progress = lambda val: DummyProgress()
st.subheader = lambda msg: None
st.caption = lambda msg: None
st.write = lambda msg="": None
st.divider = lambda: None
st.columns = lambda n: [DummyCol() for _ in range(n)]
st.plotly_chart = lambda fig, **kwargs: None
st.dataframe = lambda df, **kwargs: None

# simulate inputs
fund_code = "163406"
start_date_input = pd.to_datetime("2021-01-01").date()
end_date_input = pd.to_datetime("2026-01-01").date()
invest_freq = "每月"
invest_day = 1
monthly_amount = 1000.0
enable_smart_dca = False
take_profit_strategy = "移动止盈 (Trailing Stop)"
trail_start_pct = 30.0
trail_tolerance_pct = 8.0
sell_pct = 100.0
target_profit_pct = 99999.0
enable_reinvest = False

import pandas as pd
import akshare as ak
from datetime import datetime

# copy the exact logic
import os
cache_file = f"data/{fund_code}_history_v2.csv"
df = None
if os.path.exists(cache_file):
    df = pd.read_csv(cache_file)
else:
    print("NO DATA")

date_col = "净值日期"
nav_col = "累计净值"
df[date_col] = pd.to_datetime(df[date_col])
df[nav_col] = df[nav_col].astype(float)
df = df.sort_values(by=date_col).reset_index(drop=True)
df['MA250'] = df[nav_col].rolling(window=250, min_periods=1).mean()
df['MA_deviation'] = (df[nav_col] - df['MA250']) / df['MA250']
actual_start_date = df[date_col].min().date()
df = df[(df[date_col].dt.date >= start_date_input) & (df[date_col].dt.date <= end_date_input)].reset_index(drop=True)

df['peak_nav'] = df[nav_col].cummax()
df['fund_drawdown'] = (df[nav_col] - df['peak_nav']) / df['peak_nav']

total_shares = 0.0
total_cost = 0.0
total_invested = 0.0
cash_pool = 0.0
last_invest_period = None
last_reinvest_date = None
peak_profit_pct = 0.0
history_records = []
trade_logs = []

for idx, row in df.iterrows():
    current_date = row[date_col]
    current_nav = row[nav_col]
    fund_dd = row['fund_drawdown']
    
    current_period = (current_date.year, current_date.month)
    should_invest = current_date.day >= invest_day
    
    if current_period != last_invest_period and should_invest:
        current_multiplier = 1.0
        trade_type = "买入(定投)"
        actual_invest_amount = monthly_amount * current_multiplier
        buy_shares = actual_invest_amount / current_nav
        total_shares += buy_shares
        total_cost += actual_invest_amount
        total_invested += actual_invest_amount
        last_invest_period = current_period
        trade_logs.append({
            "日期": current_date.strftime("%Y-%m-%d"),
            "类型": trade_type,
            "净值": round(current_nav, 4),
            "发生金额": round(actual_invest_amount, 2),
            "发生份额": round(buy_shares, 2)
        })
        
    current_market_value = total_shares * current_nav
    profit_pct = 0.0
    if total_cost > 0:
        profit_pct = (current_market_value - total_cost) / total_cost
        trigger_sell = False
        sell_type_str = ""
        
        if take_profit_strategy == "静态止盈 (固定目标)":
            if profit_pct >= (target_profit_pct / 100.0):
                trigger_sell = True
                sell_type_str = "卖出(静态止盈)"
        elif take_profit_strategy == "移动止盈 (Trailing Stop)":
            if profit_pct > peak_profit_pct:
                peak_profit_pct = profit_pct
                
            if peak_profit_pct >= (trail_start_pct / 100.0):
                if profit_pct <= peak_profit_pct - (trail_tolerance_pct / 100.0):
                    trigger_sell = True
                    sell_type_str = "卖出(移动止盈)"
        
        if trigger_sell:
            sell_shares = total_shares * (sell_pct / 100.0)
            cash_out = sell_shares * current_nav
            cash_pool += cash_out
            total_shares -= sell_shares
            total_cost = total_shares * current_nav  
            current_market_value = total_shares * current_nav
            peak_profit_pct = 0.0
            trade_logs.append({
                "日期": current_date.strftime("%Y-%m-%d"),
                "类型": sell_type_str,
                "净值": round(current_nav, 4),
                "发生金额": round(cash_out, 2),
                "发生份额": round(sell_shares, 2)
            })

print("Success! Trades:", len([t for t in trade_logs if "卖出" in t["类型"]]))

