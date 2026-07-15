"""
定投回测：富国新机遇(004674) + 易方达高端制造(019034)
策略：每周四定投，动态扣款率，跑至 2025-12-31
"""
import akshare as ak
import pandas as pd
from datetime import date, timedelta
import sys
sys.path.insert(0, '/home/tianp/projects/MyFund-Quant-System')
from app.pipeline import get_dca_deduction_rate

FUNDS = {
    '004674': {'name': '富国新机遇灵活配置混合A', 'weekly': 200, 'fee': 0.0015},
    '019034': {'name': '易方达高端制造混合C', 'weekly': 100, 'fee': 0.0},
}
END_DATE = date(2025, 12, 31)

print("拉取净值...")
nav_data = {}
for code, info in FUNDS.items():
    df = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
    df['净值日期'] = pd.to_datetime(df['净值日期']).dt.date
    df = df.sort_values('净值日期').set_index('净值日期')
    nav_data[code] = df['单位净值']

common_start = max(nav_data['004674'].index[0], nav_data['019034'].index[0])

# 获取所有周四
thursdays = []
d = common_start
while d <= END_DATE:
    if d.weekday() == 3:
        thursdays.append(d)
    d += timedelta(days=1)

print(f"回测: {common_start} ~ {END_DATE}, 共 {len(thursdays)} 个周四\n")

# 逐只基金回测
all_results = {}
for code, info in FUNDS.items():
    nav = nav_data[code]
    shares, cost = 0.0, 0.0
    records = []
    
    for t in thursdays:
        dates = [d for d in nav.index if d <= t]
        if not dates:
            continue
        nav_val = nav[max(dates)]
        
        pnl_pct = ((shares * nav_val - cost) / cost * 100) if cost > 0 else 0.0
        rate = get_dca_deduction_rate(pnl_pct)
        amount = info['weekly'] * rate
        shares += (amount / (1 + info['fee'])) / nav_val
        cost += amount
        
        mv = shares * nav_val
        records.append({'date': t, 'nav': nav_val, 'amount': amount, 'shares': shares, 
                       'cost': cost, 'mv': mv, 'pnl': mv - cost, 
                       'pnl_pct': (mv - cost) / cost * 100 if cost > 0 else 0})

    df_r = pd.DataFrame(records)
    all_results[code] = df_r
    last = df_r.iloc[-1]
    print(f"{info['name']}({code}): 投入 ¥{last['cost']:,.0f} → 市值 ¥{last['mv']:,.0f} → 盈利 {last['pnl_pct']:+.1f}%")

# === 联合分析 ===
print("\n" + "=" * 60)
print("组合回测分析（两只基金合计，每周四扣款）")
print("=" * 60)

all_dates = sorted(set().union(*[set(r['date'].values) for r in all_results.values()]))

rows = []
for d in all_dates:
    total_mv = sum(all_results[c][all_results[c]['date'] == d]['mv'].values[0] for c in all_results)
    total_cost = sum(all_results[c][all_results[c]['date'] == d]['cost'].values[0] for c in all_results)
    pnl = total_mv - total_cost
    rows.append({'date': d, 'mv': total_mv, 'cost': total_cost, 'pnl': pnl,
                 'pnl_pct': pnl / total_cost * 100 if total_cost > 0 else 0})
df = pd.DataFrame(rows)

# 过滤掉前4次定投（数据太少的artifact）
min_cost = total_cost * 0.02  # 忽略前2%成本的波动
df_mature = df[df['cost'] >= min_cost].copy()

# 1. 首次进入并保持盈利
first_profit = None
profit_established = None
for _, r in df_mature.iterrows():
    if first_profit is None and r['pnl'] > 0:
        first_profit = r['date']
    if first_profit and profit_established is None:
        # 连续4周盈利才算站稳
        subset = df[(df['date'] >= r['date']) & (df['date'] <= r['date'] + timedelta(days=28))]
        if all(subset['pnl'] > 0):
            profit_established = r['date']

# 2. 盈利回吐
profit_peak_val = 0
profit_peak_date = None
giveback_start = None
for _, r in df_mature.iterrows():
    if profit_established and r['date'] >= profit_established:
        if r['pnl'] > profit_peak_val:
            profit_peak_val = r['pnl']
            profit_peak_date = r['date']
        if profit_peak_val > 0 and r['pnl'] < profit_peak_val * 0.5 and giveback_start is None:
            giveback_start = r['date']

# 3. 最难熬：最大亏损的时期
df_mature['pnl_pct'] = df_mature['pnl'] / df_mature['cost'] * 100
worst = df_mature.loc[df_mature['pnl'].idxmin()]
worst_cost = worst['cost']
print(f"\n累计投入: ¥{worst_cost:,.0f}")

# 找出从盈利转亏损的完整困难期
hard_start = None
hard_end = None
for _, r in df.iterrows():
    if r['date'] >= common_start:
        if hard_start is None and r['pnl'] < 0:
            hard_start = r['date']
        if hard_start and r['pnl'] > 0:
            # 持续3周盈利 = 结束
            subset = df[(df['date'] >= r['date']) & (df['date'] <= r['date'] + timedelta(days=21))]
            if all(subset['pnl'] > 0) and len(subset) >= 2:
                hard_end = r['date']
                break

# 4. 最大回撤（从盈利峰值算）
peak_val = 0
peak_date = None
max_dd_pct = 0
dd_start, dd_bottom, dd_bottom_date = None, None, None

for _, r in df.iterrows():
    if r['cost'] < min_cost:
        continue
    if r['pnl'] > peak_val:
        peak_val = r['pnl']
        peak_date = r['date']
    dd = (peak_val - r['pnl']) / (r['cost'] + peak_val - r['pnl']) * 100 if peak_val > 0 else 0
    if dd > max_dd_pct:
        max_dd_pct = dd
        dd_start = peak_date
        dd_bottom = r['pnl']
        dd_bottom_date = r['date']

# 修复时间
recovery_date = None
for _, r in df.iterrows():
    if r['date'] > dd_bottom_date and r['pnl'] >= peak_val:
        recovery_date = r['date']
        break

print("\n======== 回测结论 ========")
print(f"定投区间: {common_start} ~ {END_DATE}")
print(f"总投入: ¥{rows[-1]['cost']:,.0f}")
print(f"最终市值: ¥{rows[-1]['mv']:,.0f}")
print(f"最终盈利: ¥{rows[-1]['pnl']:,.0f} ({rows[-1]['pnl_pct']:+.1f}%)")

print(f"\n--- 时间线 ---")
if first_profit:
    print(f"⚡ 首次出现盈利: {first_profit}")
if profit_established:
    print(f"✅ 站稳盈利（连续4周）: {profit_established}")
if giveback_start:
    print(f"📉 盈利回吐过半: {giveback_start}（从峰值 ¥{profit_peak_val:,.0f} 回落）")

print(f"\n--- 最难熬时期 ---")
print(f"💀 最大亏损: {worst['date']}, 亏损 ¥{worst['pnl']:,.0f} ({worst['pnl_pct']:+.1f}%)，已投入 ¥{worst['cost']:,.0f}")
if hard_start and hard_end:
    days = (hard_end - hard_start).days
    print(f"   持续亏损期: {hard_start} → {hard_end}，共 {days} 天")

print(f"\n--- 最大回撤 ---")
print(f"📊 从 {dd_start} 高点 ¥{peak_val:,.0f} 开始回撤")
print(f"   底部: {dd_bottom_date}，亏损 ¥{dd_bottom:,.0f}")
print(f"   最大回撤幅度: {max_dd_pct:.1f}%")
if recovery_date:
    days_to_recover = (recovery_date - dd_bottom_date).days
    print(f"   修复时间: {recovery_date}（从底部 {days_to_recover} 天）")
else:
    print(f"   尚未完全修复")

print(f"\n--- 逐年表现 ---")
df['year'] = pd.to_datetime(df['date']).dt.year
for yr, grp in df.groupby('year'):
    l = grp.iloc[-1]
    first = grp.iloc[0]
    yr_return = (l['pnl'] - first['pnl']) / l['cost'] * 100 if l['cost'] > 0 else 0
    print(f"  {yr}年: 盈亏 {l['pnl_pct']:+.1f}%，年度收益约 {yr_return:+.1f}%")

# 各阶段详细
print(f"\n--- 各阶段盈亏（月末） ---")
df['ym'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m')
for ym, grp in df.groupby('ym'):
    l = grp.iloc[-1]
    if l['cost'] >= min_cost:
        print(f"  {ym}: 投入¥{l['cost']:,.0f} 市值¥{l['mv']:,.0f} 盈亏{l['pnl_pct']:+.1f}%")
