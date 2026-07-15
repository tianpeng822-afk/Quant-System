import pandas as pd
import akshare as ak
import numpy as np
from datetime import datetime, timedelta
import os

def get_dca_multiplier(pnl_pct):
    if pnl_pct >= 5:    return 0.50
    if pnl_pct >= 0:    return 0.70
    if pnl_pct >= -2.5: return 0.85
    if pnl_pct >= -5:   return 1.20
    if pnl_pct >= -7.5: return 1.40
    if pnl_pct >= -10:  return 1.60
    if pnl_pct >= -15:  return 1.80
    if pnl_pct >= -20:  return 1.90
    if pnl_pct >= -25:  return 1.95
    return 2.00

LADDER_LEVELS = [
    (0.25, 0.20),   # +25% → 卖 20%
    (0.40, 0.20),   # +40% → 卖 20%
    (0.60, 0.20),   # +60% → 卖 20%
    (0.95, 0.15),   # +95% → 卖 15%
    (1.50, 0.25),   # +150% → 卖 25%
]
LADDER_RESET_BELOW = 0.05

def run_backtest(fund_code, start_date_str, end_date_str):
    print(f"\n{'='*60}")
    print(f"🎯 医药基金回测: {fund_code}")
    print(f"📅 回测区间: {start_date_str} ~ {end_date_str}")
    print(f"{'='*60}")

    cache_file = f"data/{fund_code}_history_v2.csv"
    df = None

    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file)
            print(f"📦 已加载本地缓存数据 ({len(df)} 条记录)")
        except Exception as e:
            print(f"❌ 读取本地缓存失败: {e}")

    if df is None or df.empty:
        print("🌐 本地无缓存，正在从云端获取数据...")
        try:
            df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            df_accum = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")

            if df_unit is None or df_unit.empty or df_accum is None or df_accum.empty:
                print("❌ 无法获取该基金数据，请检查代码是否正确")
                return

            date_col_unit = "净值日期" if "净值日期" in df_unit.columns else df_unit.columns[0]
            date_col_accum = "净值日期" if "净值日期" in df_accum.columns else df_accum.columns[0]

            df_unit = df_unit.rename(columns={date_col_unit: "净值日期", "单位净值": "单位净值"})
            df_accum = df_accum.rename(columns={date_col_accum: "净值日期", "累计净值": "累计净值"})

            df = pd.merge(df_unit, df_accum[["净值日期", "累计净值"]], on="净值日期", how="left")
            df.attrs["name"] = df_unit.attrs.get("name", "")

            if not os.path.exists("data"):
                os.makedirs("data")
            df.to_csv(cache_file, index=False)
            print(f"✅ 云端数据获取成功，已缓存到本地")
        except Exception as e:
            print(f"❌ 数据获取失败: {e}")
            return

    date_col = "净值日期"
    nav_col = "累计净值" if "累计净值" in df.columns else "单位净值"

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df[nav_col] = df[nav_col].astype(float)
    df = df.sort_values(by=date_col).reset_index(drop=True)

    start_date = pd.to_datetime(start_date_str).date()
    end_date = pd.to_datetime(end_date_str).date()

    df = df[(df[date_col].dt.date >= start_date) & (df[date_col].dt.date <= end_date)].reset_index(drop=True)

    if df.empty:
        print("❌ 所选时间段内没有数据")
        return

    actual_start_date = df[date_col].min().date()
    if actual_start_date > start_date:
        print(f"💡 该基金成立于 {actual_start_date}，回测自成立日开始")

    fund_name = str(df.attrs.get("name", fund_code))
    print(f"\n📊 基金名称: {fund_name}")

    df['peak_nav'] = df[nav_col].cummax()
    df['fund_drawdown'] = (df[nav_col] - df['peak_nav']) / df['peak_nav']

    total_shares = 0.0
    total_cost = 0.0
    total_invested = 0.0
    cash_pool = 0.0
    last_invest_period = None
    next_level = 0

    monthly_amount = 1000.0
    invest_day = 1

    trade_logs = []
    history_records = []

    print(f"\n⚙️ 回测策略参数:")
    print(f"   定投金额: ¥{monthly_amount:.0f}/月")
    print(f"   定投日: 每月{invest_day}日")
    print(f"   阶梯止盈: {', '.join(f'+{int(t[0]*100)}%→卖{int(t[1]*100)}%' for t in LADDER_LEVELS)}")
    print(f"   重置条件: 浮盈 < {LADDER_RESET_BELOW*100:.0f}%")
    print(f"   慧定投: 开启 (盈亏率动态 0.50x~2.00x)")

    for idx, row in df.iterrows():
        current_date = row[date_col]
        current_nav = row[nav_col]

        current_period = (current_date.year, current_date.month)
        should_invest = current_date.day >= invest_day

        if current_period != last_invest_period and should_invest:
            pnl_pct = (total_shares * current_nav - total_cost) / total_cost * 100 if total_cost > 0 else 0
            dca_mult = get_dca_multiplier(pnl_pct)

            actual_invest_amount = monthly_amount * dca_mult
            buy_shares = actual_invest_amount / current_nav
            total_shares += buy_shares
            total_cost += actual_invest_amount
            total_invested += actual_invest_amount
            last_invest_period = current_period

            trade_type = "买入(定投)"
            if abs(dca_mult - 1.0) > 0.01:
                trade_type = f"买入(慧定投x{dca_mult:.2f})"

            trade_logs.append({
                "日期": current_date.strftime("%Y-%m-%d"),
                "类型": trade_type,
                "净值": round(current_nav, 4),
                "发生金额": round(actual_invest_amount, 2),
                "发生份额": round(buy_shares, 2)
            })

            if total_cost > 0:
                pp = (total_shares * current_nav - total_cost) / total_cost
                if pp < LADDER_RESET_BELOW:
                    next_level = 0

        if total_shares <= 0:
            current_market_value = 0.0
        else:
            current_market_value = total_shares * current_nav

            pp = (current_market_value - total_cost) / total_cost if total_cost > 0 else 0

            while next_level < len(LADDER_LEVELS) and pp >= LADDER_LEVELS[next_level][0] and total_shares > 0:
                threshold, sell_ratio = LADDER_LEVELS[next_level]
                sell_shares = total_shares * sell_ratio
                cash_out = sell_shares * current_nav

                total_shares -= sell_shares
                total_cost *= (1 - sell_ratio)
                cash_pool += cash_out
                next_level += 1

                trade_logs.append({
                    "日期": current_date.strftime("%Y-%m-%d"),
                    "类型": f"卖出(阶梯止盈+{int(threshold*100)}%)",
                    "净值": round(current_nav, 4),
                    "发生金额": round(cash_out, 2),
                    "发生份额": round(sell_shares, 2)
                })

                current_market_value = total_shares * current_nav
                pp = (current_market_value - total_cost) / total_cost if total_cost > 0 else 0

        history_records.append({
            "日期": current_date,
            "累计投入本金": total_invested,
            "累计变现金额": cash_pool,
            "当前持仓市值": current_market_value,
            "总权益(变现+市值)": cash_pool + current_market_value,
            "当前成本": total_cost,
            "基金净值": current_nav,
        })

    history_df = pd.DataFrame(history_records)

    history_df['equity_peak'] = history_df['总权益(变现+市值)'].cummax()
    history_df['strategy_drawdown'] = (history_df['总权益(变现+市值)'] - history_df['equity_peak']) / history_df['equity_peak'].replace(0, pd.NA) * 100
    strategy_max_dd = history_df['strategy_drawdown'].min() if not history_df.empty else 0.0

    fund_max_dd = df['fund_drawdown'].min() * 100 if not df.empty else 0.0

    final_market_value = total_shares * df.iloc[-1][nav_col]
    absolute_profit = (cash_pool + final_market_value) - total_invested
    total_return_pct = (absolute_profit / total_invested * 100) if total_invested > 0 else 0.0

    days = (df.iloc[-1][date_col] - df.iloc[0][date_col]).days
    years = days / 365.25

    cfs = []
    for log in trade_logs:
        if log["类型"].startswith("买入"):
            date_obj = datetime.strptime(log["日期"], "%Y-%m-%d").date()
            cfs.append((date_obj, -log["发生金额"]))

    final_date = df.iloc[-1][date_col].date()
    cfs.append((final_date, final_market_value + cash_pool))

    def xnpv(rate):
        if rate <= -0.9999:
            return float('inf')
        return sum([cf[1] / ((1 + rate) ** ((cf[0] - cfs[0][0]).days / 365.25)) for cf in cfs])

    try:
        import scipy.optimize
        if len(cfs) > 1:
            annual_return_pct = scipy.optimize.newton(xnpv, 0.1) * 100
        else:
            annual_return_pct = 0.0
    except:
        avg_years = years / 2
        annual_return_pct = (((final_market_value + cash_pool) / total_invested) ** (1 / avg_years) - 1) * 100 if total_invested > 0 and avg_years > 0 else 0.0

    start_nav_val = df.iloc[0][nav_col]
    end_nav_val = df.iloc[-1][nav_col]
    fund_total_return = (end_nav_val - start_nav_val) / start_nav_val * 100 if start_nav_val > 0 else 0.0
    fund_annual_return = (((end_nav_val / start_nav_val) ** (1 / years) - 1) * 100) if start_nav_val > 0 and years > 0 else 0.0

    total_alpha = total_return_pct - fund_total_return
    annual_alpha = annual_return_pct - fund_annual_return

    dd_ratio = (strategy_max_dd / fund_max_dd) if fund_max_dd < 0 else 0.0
    dd_improvement = (1 - dd_ratio) * 100 if fund_max_dd < 0 else 0.0

    sell_logs = [log for log in trade_logs if "卖出" in log["类型"]]

    print(f"\n{'='*60}")
    print(f"📈 回测结果汇总")
    print(f"{'='*60}")
    print(f"💰 累计投入本金: ¥{total_invested:,.0f}")
    print(f"💵 可用止盈资金: ¥{cash_pool:,.0f}")
    print(f"📦 期末剩余市值: ¥{final_market_value:,.0f}")
    print(f"\n📊 收益表现:")
    print(f"   绝对总收益: {'¥' + str(format(absolute_profit, ',.0f'))} {'🔴' if absolute_profit >= 0 else '🟢'}")
    print(f"   策略累计收益率: {total_return_pct:.2f}% {'🔴' if total_return_pct >= 0 else '🟢'}")
    print(f"   基金本身收益率: {fund_total_return:.2f}%")
    print(f"   超额收益(Alpha): {total_alpha:.2f}% {'🔴' if total_alpha >= 0 else '🟢'}")
    print(f"\n📅 年化收益:")
    print(f"   策略平均年化: {annual_return_pct:.2f}%")
    print(f"   基金本身年化: {fund_annual_return:.2f}%")
    print(f"   超额年化: {annual_alpha:.2f}% {'🔴' if annual_alpha >= 0 else '🟢'}")
    print(f"\n📉 风险指标:")
    print(f"   策略最大回撤: {strategy_max_dd:.2f}%")
    print(f"   基金历史最大回撤: {fund_max_dd:.2f}%")
    print(f"   抗风险能力(回撤改善): +{dd_improvement:.1f}%")

    print(f"\n📝 止盈记录 ({len(sell_logs)}次):")
    for log in sell_logs:
        print(f"   {log['日期']} - {log['类型']} - 净值:{log['净值']:.4f} - 卖出金额:¥{log['发生金额']:,.2f}")

    print(f"\n{'='*60}")

    return {
        'fund_code': fund_code,
        'fund_name': fund_name,
        'total_invested': total_invested,
        'cash_pool': cash_pool,
        'final_market_value': final_market_value,
        'absolute_profit': absolute_profit,
        'total_return_pct': total_return_pct,
        'annual_return_pct': annual_return_pct,
        'strategy_max_dd': strategy_max_dd,
        'fund_max_dd': fund_max_dd,
        'total_alpha': total_alpha,
        'sell_count': len(sell_logs),
        'years': years
    }

if __name__ == "__main__":
    today = datetime.today()
    five_years_ago = today - timedelta(days=365*5)

    results = []
    medical_funds = [
        ("001171", "工银养老产业股票A"),
        ("000854", "鹏华养老产业股票"),
    ]

    for fund_code, fund_name in medical_funds:
        print(f"\n{'#'*80}")
        print(f"正在测试: {fund_name} ({fund_code})")
        print(f"{'#'*80}")
        try:
            result = run_backtest(fund_code, five_years_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
            if result:
                results.append(result)
        except Exception as e:
            print(f"❌ 测试 {fund_code} 失败: {e}")
            continue

    print(f"\n{'='*80}")
    print(f"📊 医药基金回测对比汇总 (阶梯止盈策略)")
    print(f"{'='*80}")
    print(f"{'基金代码':<12} {'基金名称':<20} {'累计收益':<12} {'年化收益':<10} {'策略回撤':<10} {'基金回撤':<10} {'Alpha':<10}")
    print(f"{'='*80}")

    for r in results:
        print(f"{r['fund_code']:<12} {r['fund_name'][:20]:<20} {r['total_return_pct']:>7.2f}% {'🔴' if r['total_return_pct'] >= 0 else '🟢'} {r['annual_return_pct']:>8.2f}% {r['strategy_max_dd']:>8.2f}% {r['fund_max_dd']:>8.2f}% {r['total_alpha']:>8.2f}%")

    print(f"{'='*80}")