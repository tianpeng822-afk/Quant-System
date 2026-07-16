import pandas as pd
from datetime import datetime, timedelta

LADDER_SELL = [(0.25, 0.20), (0.40, 0.20), (0.60, 0.20), (0.95, 0.15), (1.50, 0.25)]
LADDER_RESET_BELOW = 0.05
LADDER_BUY = [(0.20, 0.15), (0.30, 0.15)]
INVEST_DAY = 2
INVEST_BASE = 200
INITIAL_AMOUNT = 5000
FUND_CODE = '004674'

def get_dca_deduction_rate(pnl_pct):
    if pnl_pct >= 25: return 0.50
    if pnl_pct >= 20: return 0.525
    if pnl_pct >= 15: return 0.55
    if pnl_pct >= 10: return 0.60
    if pnl_pct >= 7.5: return 0.70
    if pnl_pct >= 5: return 0.80
    if pnl_pct >= 2.5: return 0.90
    if pnl_pct >= -2.5: return 1.00
    if pnl_pct >= -5: return 1.20
    if pnl_pct >= -7.5: return 1.40
    if pnl_pct >= -10: return 1.60
    if pnl_pct >= -15: return 1.80
    if pnl_pct >= -20: return 1.90
    if pnl_pct >= -25: return 1.95
    return 2.00

def get_data(code, start, end):
    cache = '/home/tianp/projects/MyFund-Quant-System/data/' + code + '_history_v2.csv'
    df = pd.read_csv(cache)
    df['净值日期'] = pd.to_datetime(df['净值日期'])
    df = df[(df['净值日期'] >= start) & (df['净值日期'] <= end)].dropna(subset=['单位净值'])
    df['单位净值'] = pd.to_numeric(df['单位净值'])
    df = df.sort_values('净值日期').reset_index(drop=True)
    return df

today = datetime.today()
start = (today - timedelta(days=365*5)).strftime('%Y-%m-%d')
end = today.strftime('%Y-%m-%d')
df = get_data(FUND_CODE, start, end)
print('回测区间:', start, '~', end)
print('数据条数:', len(df))
print()

shares = 0.0
cost = 0.0
invested = 0.0
cash = 0.0
last_period = None
next_sell_level = 0
next_buy_level = 0
peak_nav = 0.0
buy_count = 0
sell_count = 0
daily_values = []

init_nav = df.iloc[0]['单位净值']
init_shares = INITIAL_AMOUNT / init_nav
shares += init_shares
cost += INITIAL_AMOUNT
invested += INITIAL_AMOUNT
peak_nav = init_nav
print('初始建仓: %d元 @ %.4f, 份额=%.2f' % (INITIAL_AMOUNT, init_nav, init_shares))

for idx, row in df.iterrows():
    dt = row['净值日期']
    nav = row['单位净值']
    period = (dt.isocalendar()[0], dt.isocalendar()[1])

    if period != last_period and dt.weekday() == INVEST_DAY:
        if cost > 0 and shares > 0:
            avg_cost = cost / shares
            pnl_pct = (nav - avg_cost) / avg_cost * 100
        else:
            pnl_pct = 0
        rate = get_dca_deduction_rate(pnl_pct)
        actual_amount = INVEST_BASE * rate
        buy_shares = actual_amount / nav
        shares += buy_shares
        cost += actual_amount
        invested += actual_amount
        last_period = period
        buy_count += 1

    if shares <= 0:
        continue

    mv = shares * nav
    avg_cost = cost / shares if shares > 0 else 0
    pnl_pct = (nav - avg_cost) / avg_cost if avg_cost > 0 else 0

    if nav > peak_nav:
        peak_nav = nav

    dd_pct = (peak_nav - nav) / peak_nav if peak_nav > 0 else 0

    if pnl_pct < LADDER_RESET_BELOW:
        next_sell_level = 0

    sell_triggered = False
    while next_sell_level < len(LADDER_SELL) and pnl_pct >= LADDER_SELL[next_sell_level][0]:
        threshold, sell_ratio = LADDER_SELL[next_sell_level]
        sell_shares = shares * sell_ratio
        sell_amount = sell_shares * nav
        sell_cost = cost * sell_ratio
        cash += sell_amount
        shares -= sell_shares
        cost -= sell_cost
        next_sell_level += 1
        sell_count += 1
        sell_triggered = True
        new_avg = cost / shares if shares > 0 else 0
        new_pnl = (nav - new_avg) / new_avg * 100 if new_avg > 0 else 0
        print('%s SELL 止盈+%d%%: 净值=%.4f 卖出份额=%.2f(含补仓份额) 卖出金额=%.0f元 剩余份额=%.2f 剩余成本=%.0f 新成本价=%.4f 新浮盈=%.1f%%' % (dt.strftime('%Y-%m-%d'), int(threshold*100), nav, sell_shares, sell_amount, shares, cost, new_avg, new_pnl))
        break

    if not sell_triggered:
        while next_buy_level < len(LADDER_BUY) and dd_pct >= LADDER_BUY[next_buy_level][0]:
            if pnl_pct > 0:
                # 浮盈时回撤 -> 减仓25%锁利润
                sell_shares_dd = shares * 0.25
                sell_amount_dd = sell_shares_dd * nav
                sell_cost_dd = cost * 0.25
                cash += sell_amount_dd
                shares -= sell_shares_dd
                cost -= sell_cost_dd
                next_buy_level += 1
                sell_count += 1
                sell_triggered = True
                new_avg = cost / shares if shares > 0 else 0
                new_pnl = (nav - new_avg) / new_avg * 100 if new_avg > 0 else 0
                print('%s SELL 回撤%d%%减仓: 净值=%.4f 浮盈=%.1f%% 减仓份额=%.2f 卖出=%.0f元 剩余份额=%.2f 新成本价=%.4f 新浮盈=%.1f%%' % (dt.strftime('%Y-%m-%d'), int(dd_pct*100), nav, pnl_pct*100, sell_shares_dd, sell_amount_dd, shares, new_avg, new_pnl))
            else:
                # 浮亏时回撤 -> 补仓15%摊成本
                _, buy_ratio = LADDER_BUY[next_buy_level]
                buy_amount = mv * buy_ratio
                buy_shares = buy_amount / nav
                shares += buy_shares
                cost += buy_amount
                invested += buy_amount
                next_buy_level += 1
                buy_count += 1
                new_avg = cost / shares if shares > 0 else 0
                new_pnl = (nav - new_avg) / new_avg * 100 if new_avg > 0 else 0
                print('%s BUY 回撤%d%%补仓: 净值=%.4f 浮亏=%.1f%% 补仓=%.0f元 份额+%.2f 总份额=%.2f 新成本价=%.4f 新浮盈=%.1f%%' % (dt.strftime('%Y-%m-%d'), int(dd_pct*100), nav, pnl_pct*100, buy_amount, buy_shares, shares, new_avg, new_pnl))
            break

    if nav >= peak_nav:  # 净值创新高才重置回撤阶梯
        next_buy_level = 0

    # 记录每日总价值
    daily_values.append((dt, cash + shares * nav))
    # 月度快照（2024-02到2025-07）
    if dt.day <= 7 and dt >= pd.Timestamp('2024-02-01') and dt <= pd.Timestamp('2025-07-17'):
        if '_last_snap_month' not in globals() or _last_snap_month != dt.strftime('%Y-%m'):
            _last_snap_month = dt.strftime('%Y-%m')
            print('%s 快照: 净值=%.4f 份额=%.2f 成本=%.0f 成本价=%.4f 浮盈=%.1f%% 回撤=%.1f%% 总价值=%.0f' % (dt.strftime('%Y-%m-%d'), nav, shares, cost, avg_cost, pnl_pct*100, dd_pct*100, cash + shares * nav))

final_nav = df.iloc[-1]['单位净值']
final_mv = shares * final_nav
total_value = cash + final_mv
profit = total_value - invested
ret = profit / invested * 100 if invested > 0 else 0

# ====== 计算策略最大回撤 ======
print()
print('=' * 80)
print('策略最大回撤分析：')
print('=' * 80)
peak_value = 0
max_dd = 0
max_dd_date = None
peak_date = None
for dv in daily_values:
    dt, tv = dv
    if tv > peak_value:
        peak_value = tv
        peak_date = dt
    dd = (peak_value - tv) / peak_value if peak_value > 0 else 0
    if dd > max_dd:
        max_dd = dd
        max_dd_date = dt

print('策略峰值总价值: %.0f元 (%s)' % (peak_value, peak_date.strftime('%Y-%m-%d') if peak_date else 'N/A'))
print('策略最大回撤:   %.2f%% (%s)' % (max_dd * 100, max_dd_date.strftime('%Y-%m-%d') if max_dd_date else 'N/A'))

# 基金净值最大回撤
nav_peak = 0
nav_max_dd = 0
nav_max_dd_date = None
for idx, row in df.iterrows():
    nav = row['单位净值']
    dt = row['净值日期']
    if nav > nav_peak:
        nav_peak = nav
    dd = (nav_peak - nav) / nav_peak if nav_peak > 0 else 0
    if dd > nav_max_dd:
        nav_max_dd = dd
        nav_max_dd_date = dt
print('基金净值最大回撤: %.2f%% (%s)' % (nav_max_dd * 100, nav_max_dd_date.strftime('%Y-%m-%d') if nav_max_dd_date else 'N/A'))

print()
print('=' * 80)
print('回测结果 - 广发科技先锋 (004674)')
print('=' * 80)
print('初始建仓: %d元' % INITIAL_AMOUNT)
print('定投基数: %d元/周 (周三)' % INVEST_BASE)
print('累计投入: %.0f元' % invested)
print('期末市值: %.0f元' % final_mv)
print('现金池:   %.0f元' % cash)
print('总价值:   %.0f元' % total_value)
print('绝对收益: %.0f元' % profit)
print('收益率:   %.2f%%' % ret)
print('策略最大回撤: %.2f%%' % (max_dd * 100))
print('基金净值最大回撤: %.2f%%' % (nav_max_dd * 100))
print('买入次数: %d (含定投+补仓)' % buy_count)
print('卖出次数: %d' % sell_count)
print('期末份额: %.2f' % shares)
print('期末成本: %.0f元' % cost)
if shares > 0:
    print('期末成本价: %.4f' % (cost/shares))
