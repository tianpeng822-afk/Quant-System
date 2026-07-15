import pandas as pd
import akshare as ak
from datetime import datetime, timedelta

def run_backtest(fund_code, start_date_str, end_date_str):
    df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df_accum = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
    
    date_col_unit = "净值日期" if "净值日期" in df_unit.columns else df_unit.columns[0]
    date_col_accum = "净值日期" if "净值日期" in df_accum.columns else df_accum.columns[0]
    
    df_unit = df_unit.rename(columns={date_col_unit: "净值日期", "单位净值": "单位净值"})
    df_accum = df_accum.rename(columns={date_col_accum: "净值日期", "累计净值": "累计净值"})
    
    df = pd.merge(df_unit, df_accum[["净值日期", "累计净值"]], on="净值日期", how="left")
    
    df["净值日期"] = pd.to_datetime(df["净值日期"])
    df["累计净值"] = df["累计净值"].astype(float)
    df = df.sort_values(by="净值日期").reset_index(drop=True)
    
    start_date = pd.to_datetime(start_date_str).date()
    end_date = pd.to_datetime(end_date_str).date()
    
    df = df[(df["净值日期"].dt.date >= start_date) & (df["净值日期"].dt.date <= end_date)].reset_index(drop=True)
    
    df['peak_nav'] = df["累计净值"].cummax()
    df['fund_drawdown'] = (df["累计净值"] - df['peak_nav']) / df['peak_nav']
    
    total_shares = 0.0
    total_cost = 0.0
    total_invested = 0.0
    cash_pool = 0.0
    last_invest_period = None
    
    monthly_amount = 1000.0
    target_ratio = 0.20
    sell_ratio = 0.50
    
    trade_logs = []
    
    for idx, row in df.iterrows():
        current_date = row["净值日期"]
        current_nav = row["累计净值"]
        
        current_period = (current_date.year, current_date.month)
        should_invest = current_date.day >= 1 # 每月1号之后定投
        
        if current_period != last_invest_period and should_invest:
            buy_shares = monthly_amount / current_nav
            total_shares += buy_shares
            total_cost += monthly_amount
            total_invested += monthly_amount
            last_invest_period = current_period
            trade_logs.append(f"{current_date.date()} 买入 {monthly_amount}元, 均价 {current_nav:.4f}")
            
        current_market_value = total_shares * current_nav
        if total_cost > 0:
            profit_pct = (current_market_value - total_cost) / total_cost
            if profit_pct >= target_ratio:
                sell_shares = total_shares * sell_ratio
                cash_out = sell_shares * current_nav
                cash_pool += cash_out
                total_shares -= sell_shares
                total_cost = total_shares * current_nav
                trade_logs.append(f"{current_date.date()} 触发止盈! 卖出 {cash_out:.2f}元, 收益率 {profit_pct*100:.2f}%")
                
    final_market_value = total_shares * df.iloc[-1]["累计净值"]
    absolute_profit = (cash_pool + final_market_value) - total_invested
    
    print(f"回测基金: {fund_code}")
    print(f"回测区间: {start_date_str} to {end_date_str}")
    print(f"累计投入本金: {total_invested:.2f}")
    print(f"期末剩余市值: {final_market_value:.2f}")
    print(f"已落袋现金池: {cash_pool:.2f}")
    print(f"绝对总收益: {absolute_profit:.2f}")
    print(f"策略累计收益率: {absolute_profit / total_invested * 100:.2f}%")
    print("\n止盈记录:")
    for log in [l for l in trade_logs if "触发止盈" in l]:
        print(log)

today = datetime.today()
five_years_ago = today - timedelta(days=365*5)
run_backtest("163406", five_years_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
run_backtest("510300", five_years_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
