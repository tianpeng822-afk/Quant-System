import pandas as pd
from datetime import datetime, timedelta

SELL_THRESHOLD = 0.15
SELL_RATIO = 0.20
BUY_THRESHOLD = -0.05
BUY_RATIO = 0.20
CLEAR_THRESHOLD = -0.25
ACTION_COOLDOWN = 0.02

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
last_action_pnl = None
buy_count = 0
sell_count = 0
clear_count = 0
invest_count = 0
daily_values = []

init_nav = df.iloc[0]['单位净值']
init_shares = INITIAL_AMOUNT / init_nav
shares += init_shares
cost += INITIAL_AMOUNT
invested += INITIAL_AMOUNT
print('初始建仓: %d元 @ %.4f, 份额=%.2f' % (INITIAL_AMOUNT, init_nav, init_shares))
print()

for idx, row in df.iterrows():
    dt = row['净值日期']
    nav = row['单位净值']
    period = (dt.isocalendar()[0], dt.isocalendar()[1])

    if shares > 0 and cost > 0:
        avg_cost = cost / shares
        pnl_pct = (nav - avg_cost) / avg_cost
    else:
        avg_cost = 0
        pnl_pct = 0

    if shares > 0 and pnl_pct <= CLEAR_THRESHOLD:
        sell_amount = shares * nav
        cash += sell_amount
        print('%s CLEAR 清仓: 净值=%.4f 盈亏率=%.1f%% 清仓份额=%.2f 清仓金额=%.0f元 现金池=%.0f' % (dt.strftime('%Y-%m-%d'), nav, pnl_pct*100, shares, sell_amount, cash))
        shares = 0
        cost = 0
        last_action_pnl = None
        clear_count += 1

    if period != last_period and dt.weekday() == INVEST_DAY:
        if shares > 0 and cost > 0:
            avg_cost = cost / shares
            pnl_for_rate = (nav - avg_cost) / avg_cost * 100
        else:
            pnl_for_rate = 0
        rate = get_dca_deduction_rate(pnl_for_rate)
        actual_amount = INVEST_BASE * rate
        buy_shares = actual_amount / nav
        shares += buy_shares
        cost += actual_amount
        invested += actual_amount
        last_period = period
        invest_count += 1
        print('%s INVEST 定投: 净值=%.4f 扣款率=%.2f 定投金额=%.0f元 买入份额=%.2f 累计份额=%.2f 累计成本=%.0f 累计投入=%.0f' % (dt.strftime('%Y-%m-%d'), nav, rate, actual_amount, buy_shares, shares, cost, invested))

    if shares <= 0:
        daily_values.append((dt, cash + shares * nav))
        continue

    avg_cost = cost / shares
    pnl_pct = (nav - avg_cost) / avg_cost

    if last_action_pnl is None:
        cooldown_ok = True
    else:
        cooldown_ok = abs(pnl_pct - last_action_pnl) >= ACTION_COOLDOWN

    if pnl_pct >= SELL_THRESHOLD and cooldown_ok:
        sell_shares = shares * SELL_RATIO
        sell_amount = sell_shares * nav
        sell_cost = cost * SELL_RATIO
        cash += sell_amount
        shares -= sell_shares
        cost -= sell_cost
        last_action_pnl = pnl_pct
        sell_count += 1
        new_avg = cost / shares if shares > 0 else 0
        new_pnl = (nav - new_avg) / new_avg if new_avg > 0 else 0
        print('%s SELL 减仓: 净值=%.4f 盈亏率=%.1f%% 减仓比例=%d%% 卖出份额=%.2f 卖出金额=%.0f元 剩余份额=%.2f 剩余成本=%.0f 新成本价=%.4f 新盈亏率=%.1f%% 现金池=%.0f' % (dt.strftime('%Y-%m-%d'), nav, pnl_pct*100, int(SELL_RATIO*100), sell_shares, sell_amount, shares, cost, new_avg, new_pnl*100, cash))
    elif pnl_pct <= BUY_THRESHOLD and cooldown_ok:
        mv = shares * nav
        buy_amount = mv * BUY_RATIO
        buy_shares = buy_amount / nav
        shares += buy_shares
        cost += buy_amount
        invested += buy_amount
        last_action_pnl = pnl_pct
        buy_count += 1
        new_avg = cost / shares if shares > 0 else 0
        new_pnl = (nav - new_avg) / new_avg if new_avg > 0 else 0
        print('%s BUY 加仓: 净值=%.4f 盈亏率=%.1f%% 加仓比例=%d%% 加仓金额=%.0f元 买入份额=%.2f 总份额=%.2f 总成本=%.0f 新成本价=%.4f 新盈亏率=%.1f%% 累计投入=%.0f' % (dt.strftime('%Y-%m-%d'), nav, pnl_pct*100, int(BUY_RATIO*100), buy_amount, buy_shares, shares, cost, new_avg, new_pnl*100, invested))

    daily_values.append((dt, cash + shares * nav))

final_nav = df.iloc[-1]['单位净值']
final_mv = shares * final_nav
total_value = cash + final_mv
profit = total_value - invested
ret = profit / invested * 100 if invested > 0 else 0

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
print('回测结果 - FUND_CODE=%s' % FUND_CODE)
print('=' * 80)
print('初始建仓: %d元' % INITIAL_AMOUNT)
print('定投基数: %d元/周 (周三, 动态扣款率)' % INVEST_BASE)
print('累计投入: %.0f元' % invested)
print('期末市值: %.0f元' % final_mv)
print('现金池:   %.0f元' % cash)
print('总价值:   %.0f元' % total_value)
print('绝对收益: %.0f元' % profit)
print('收益率:   %.2f%%' % ret)
print('策略最大回撤: %.2f%%' % (max_dd * 100))
print('基金净值最大回撤: %.2f%%' % (nav_max_dd * 100))
print('定投次数: %d' % invest_count)
print('加仓次数: %d (浮亏>=5%%触发)' % buy_count)
print('减仓次数: %d (浮盈>=15%%触发)' % sell_count)
print('清仓次数: %d (浮亏>=25%%触发)' % clear_count)
print('期末份额: %.2f' % shares)
print('期末成本: %.0f元' % cost)
if shares > 0:
    print('期末成本价: %.4f' % (cost/shares))
