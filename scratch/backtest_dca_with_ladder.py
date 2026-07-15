"""
定投回测（含阶梯止盈）：富国新机遇(004674) + 易方达高端制造(019034)
每周四定投 + 阶梯止盈卖出，含持仓市值与现金分立
"""
import akshare as ak
import pandas as pd
from datetime import date, timedelta
import sys
sys.path.insert(0, '/home/tianp/projects/MyFund-Quant-System')
from app.pipeline import get_dca_deduction_rate

FUNDS = {
    '004674': {'name': '富国新机遇', 'weekly': 200, 'fee': 0.0015},
    '019034': {'name': '易方达高端制造', 'weekly': 100, 'fee': 0.0},
}
END_DATE = date(2025, 12, 31)
LADDER = [(0.25, 0.20), (0.40, 0.20), (0.60, 0.20), (0.95, 0.15), (1.50, 0.25)]
LADDER_RESET = 0.05

print("拉取净值...")
nav_data = {}
for code, info in FUNDS.items():
    df = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
    df['净值日期'] = pd.to_datetime(df['净值日期']).dt.date
    df = df.sort_values('净值日期').set_index('净值日期')
    nav_data[code] = df['单位净值']

common_start = max(nav_data['004674'].index[0], nav_data['019034'].index[0])
thursdays = []
d = common_start
while d <= END_DATE:
    if d.weekday() == 3:
        thursdays.append(d)
    d += timedelta(days=1)

print(f"回测: {common_start} ~ {END_DATE}, 共 {len(thursdays)} 个周四\n")

sell_events = []
all_results_list = []

for code, info in FUNDS.items():
    nav = nav_data[code]
    shares = 0.0
    total_cost = 0.0       # 持仓剩余成本
    cash = 0.0              # 止盈落袋现金（含已实现盈亏）
    total_outflow = 0.0     # 总投入现金
    total_inflow = 0.0      # 止盈卖出总收入
    triggered_levels = set()
    last_reset = None
    records = []

    for t in thursdays:
        dates = [d for d in nav.index if d <= t]
        if not dates:
            continue
        nav_val = nav[max(dates)]

        # 当前盈亏
        if shares > 0:
            mv = shares * nav_val
            pnl = mv - total_cost
            pnl_pct = (pnl / total_cost * 100)
        else:
            mv, pnl, pnl_pct = 0, 0, 0

        # 阶梯止盈
        if pnl_pct < LADDER_RESET * 100 and triggered_levels:
            triggered_levels = set()
            last_reset = t

        new_triggers = []
        for idx, (th, sr) in enumerate(LADDER):
            if idx not in triggered_levels and pnl_pct >= th * 100:
                triggered_levels.add(idx)
                new_triggers.append(idx)

        # 执行卖出：卖出的钱进入现金账户
        for idx_sell in new_triggers:
            sell_sr = LADDER[idx_sell][1]
            sell_shares = shares * sell_sr
            sell_amount = sell_shares * nav_val
            sell_cost_rel = total_cost * sell_sr
            realized = sell_amount - sell_cost_rel

            shares -= sell_shares
            total_cost -= sell_cost_rel
            cash += sell_amount        # 卖出的钱进现金
            total_inflow += sell_amount

            sell_events.append({
                'date': t, 'fund': info['name'], 'code': code,
                'level': f"+{int(LADDER[idx_sell][0]*100)}%",
                'sell_amount': round(sell_amount, 2),
                'realized': round(realized, 2),
            })

            mv = shares * nav_val
            pnl = mv - total_cost
            pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0

        # 定投（从现金中扣款，没现金就用自己的钱投）
        dca_pnl_pct = ((shares * nav_val - total_cost) / total_cost * 100) if total_cost > 0 else 0
        rate = get_dca_deduction_rate(dca_pnl_pct)
        amount = info['weekly'] * rate
        bought = (amount / (1 + info['fee'])) / nav_val
        shares += bought
        total_cost += amount
        total_outflow += amount

        mv = shares * nav_val
        avg_cost = total_cost / shares if shares > 0 else 0

        records.append({
            'date': t, 'nav': nav_val, 'shares': shares,
            'cost': total_cost,
            'avg_cost': avg_cost,
            'mv': round(mv, 2),
            'cash_in': round(cash, 2),       # 止盈已落袋现金
            'total_in': round(total_outflow, 2),  # 总投入
            'float_pnl': round(mv - total_cost, 2),
        })

    df_r = pd.DataFrame(records)
    all_results_list.append((info['name'], code, df_r))

    last = df_r.iloc[-1]
    print(f"{info['name']}({code}):")

    # 统计止盈次数
    fund_sells = [s for s in sell_events if s['code'] == code]
    print(f"  总投入: ¥{last['total_in']:,.0f}")
    print(f"  持仓市值: ¥{last['mv']:,.0f}")
    print(f"  止盈落袋: ¥{last['cash_in']:,.0f}")
    print(f"  总资产(持仓+现金): ¥{last['mv'] + last['cash_in']:,.0f}")
    print(f"  净盈亏: ¥{last['mv'] + last['cash_in'] - last['total_in']:,.0f} ({(last['mv'] + last['cash_in'] - last['total_in']) / last['total_in'] * 100:+.1f}%)")
    print(f"  触发止盈: {len(fund_sells)} 次")
    for s in fund_sells:
        print(f"    {s['date']} {s['level']}档 卖出¥{s['sell_amount']:,.0f}")

print(f"\n{'='*60}")
print(f"组合资产变化（每月末）")
print(f"{'='*60}")
print(f"{'日期':10s} {'总投入':>8s} {'持仓市值':>10s} {'止盈现金':>10s} {'总资产':>10s} {'盈亏':>10s}")
print(f"{'─'*10} {'─'*8} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")

# 合并两条时间线
all_dates = sorted(set().union(*[set(r['date'].values) for _, _, r in all_results_list]))
month_ends = {}
for d in all_dates:
    ym = d.strftime('%Y-%m')
    month_ends[ym] = d

for ym, d in sorted(month_ends.items()):
    # 取该月最后一个周四
    month_dates = [x for x in all_dates if x.strftime('%Y-%m') == ym]
    if not month_dates:
        continue
    last_d = max(month_dates)

    total_in = sum(r[r['date'] == last_d]['total_in'].values[0] if len(r[r['date'] == last_d]) > 0 else 0 for _, _, r in all_results_list)
    total_mv = sum(r[r['date'] == last_d]['mv'].values[0] if len(r[r['date'] == last_d]) > 0 else 0 for _, _, r in all_results_list)
    total_cash = sum(r[r['date'] == last_d]['cash_in'].values[0] if len(r[r['date'] == last_d]) > 0 else 0 for _, _, r in all_results_list)

    total_assets = total_mv + total_cash
    pnl = total_assets - total_in
    print(f"{ym:>8s} ¥{total_in:>7,.0f} ¥{total_mv:>8,.0f} ¥{total_cash:>8,.0f} ¥{total_assets:>8,.0f} ¥{pnl:>+8,.0f}")

print(f"\n{'='*60}")
print(f"最终结果")
print(f"{'='*60}")
total_in_final = sum(r.iloc[-1]['total_in'] for _, _, r in all_results_list)
total_mv_final = sum(r.iloc[-1]['mv'] for _, _, r in all_results_list)
total_cash_final = sum(r.iloc[-1]['cash_in'] for _, _, r in all_results_list)
total_assets_final = total_mv_final + total_cash_final
pnl_final = total_assets_final - total_in_final

print(f"总投入: ¥{total_in_final:,.0f}")
print(f"持仓市值: ¥{total_mv_final:,.0f}")
print(f"止盈落袋现金: ¥{total_cash_final:,.0f}")
print(f"总资产(持仓+现金): ¥{total_assets_final:,.0f}")
print(f"净盈亏: ¥{pnl_final:,.0f} ({pnl_final/total_in_final*100:+.1f}%)")
print(f"共触发止盈: {len(sell_events)} 次")
