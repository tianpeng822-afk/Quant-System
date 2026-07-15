import pandas as pd
import numpy as np

# Load data
df_A = pd.read_csv('data/003376_history_v2.csv')
df_B = pd.read_csv('data/000051_history_v2.csv')
df_A['净值日期'] = pd.to_datetime(df_A['净值日期'])
df_B['净值日期'] = pd.to_datetime(df_B['净值日期'])
df_merged = pd.merge(df_A, df_B, on='净值日期', how='outer')
df_merged = df_merged.sort_values('净值日期').ffill().dropna().reset_index(drop=True)

start_dt = pd.to_datetime('2017-01-01')
df_merged = df_merged[df_merged['净值日期'] >= start_dt].reset_index(drop=True)

monthly_amount = 2000.0
target_rA, target_rB = 0.7, 0.3

results = []

for rebalance_month in range(1, 13):
    shares_A, shares_B = 0.0, 0.0
    total_invested = 0.0
    portfolio_shares = 0.0
    
    last_invest_period = None
    last_rebalance_year = None
    
    history_records = []
    
    for idx, row in df_merged.iterrows():
        current_date = row['净值日期']
        nav_A = float(row['累计净值_x'])
        nav_B = float(row['累计净值_y'])
        
        current_period = (current_date.year, current_date.month)
        
        total_market_value = shares_A * nav_A + shares_B * nav_B
        current_portfolio_nav = total_market_value / portfolio_shares if portfolio_shares > 0 else 1.0
        
        trigger_rebalance = False
        
        # Annual rebalance on the first trading day of the chosen month
        if current_date.month == rebalance_month and current_date.year != last_rebalance_year:
            if total_invested > 0:
                trigger_rebalance = True
            last_rebalance_year = current_date.year
                
        if trigger_rebalance and total_invested > 0:
            shares_A = (total_market_value * target_rA) / nav_A
            shares_B = (total_market_value * target_rB) / nav_B
            
        # Monthly invest
        if current_period != last_invest_period:
            invest_A = monthly_amount * target_rA
            invest_B = monthly_amount * target_rB
            
            shares_A += invest_A / nav_A
            shares_B += invest_B / nav_B
            
            total_invested += monthly_amount
            last_invest_period = current_period
            portfolio_shares += monthly_amount / current_portfolio_nav
            
        total_mv = shares_A * nav_A + shares_B * nav_B
        daily_portfolio_nav = total_mv / portfolio_shares if portfolio_shares > 0 else 1.0
        
        history_records.append({
            "nav": daily_portfolio_nav,
            "mv": total_mv
        })
        
    history_df = pd.DataFrame(history_records)
    history_df['max_nav'] = history_df['nav'].cummax()
    history_df['drawdown'] = (history_df['nav'] - history_df['max_nav']) / history_df['max_nav']
    
    max_dd = history_df['drawdown'].min() * 100
    final_mv = history_df.iloc[-1]['mv']
    absolute_profit = final_mv - total_invested
    
    results.append({
        "Month": rebalance_month,
        "Final MV": final_mv,
        "Total Profit": absolute_profit,
        "Max Drawdown (%)": max_dd
    })

res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))
