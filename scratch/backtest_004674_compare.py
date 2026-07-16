"""
富国新机遇(004674) 回测对比：
  策略A: 阶梯止盈 + 动态定投
  策略B: 阶梯止盈 + 移动止盈(回撤18%) + 动态定投
买入逻辑不变（每周四定投，动态扣款率），只对比卖出策略差异。
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import date, timedelta
import sys
sys.path.insert(0, '/workspace')
from app.pipeline import get_dca_deduction_rate

# ── 配置 ──────────────────────────────────────────────────
FUND_CODE = '004674'
FUND_NAME = '富国新机遇'
WEEKLY = 200          # 每周定投基础金额
FEE = 0.0015          # 申购费率 0.15%
LADDER = [(0.25, 0.20), (0.40, 0.20), (0.60, 0.20), (0.95, 0.15), (1.50, 0.25)]
LADDER_RESET = 0.05
TRAILING_TOLERANCE = 18.0  # 移动止盈回撤容忍度（百分点）
TRAILING_SELL_RATIO = 0.20  # 移动止盈每次卖出比例

# ── 拉取完整历史净值 ──────────────────────────────────────
print("拉取 004674 完整净值数据...")
df = ak.fund_open_fund_info_em(symbol=FUND_CODE, indicator='单位净值走势')
df['净值日期'] = pd.to_datetime(df['净值日期']).dt.date
df = df.sort_values('净值日期').reset_index(drop=True)
print(f"数据范围: {df['净值日期'].iloc[0]} ~ {df['净值日期'].iloc[-1]}, 共 {len(df)} 条")

# 生成所有周四
all_dates = df['净值日期'].tolist()
nav_series = df.set_index('净值日期')['单位净值']
start_date = all_dates[0]
end_date = all_dates[-1]

thursdays = []
d = start_date
while d <= end_date:
    if d.weekday() == 3:
        thursdays.append(d)
    d += timedelta(days=1)

# 过滤：确保每个周四有净值数据（取最近的交易日）
trade_thursdays = []
for t in thursdays:
    dates = [x for x in all_dates if x <= t]
    if dates:
        trade_thursdays.append(t)

print(f"回测区间: {trade_thursdays[0]} ~ {trade_thursdays[-1]}, 共 {len(trade_thursdays)} 个定投日\n")


def get_nav(t):
    """获取日期 t 当天或之前最近的净值"""
    dates = [x for x in all_dates if x <= t]
    if dates:
        return float(nav_series[max(dates)])
    return None


def run_backtest(use_trailing: bool):
    """运行回测，返回 records 列表和 sell_events 列表"""
    shares = 0.0
    total_cost = 0.0
    cash = 0.0
    total_outflow = 0.0
    triggered_levels = set()
    peak_pnl_pct = 0.0  # 历史最高浮盈率
    records = []
    sell_events = []

    for t in trade_thursdays:
        nav_val = get_nav(t)
        if nav_val is None:
            continue

        # 计算当前盈亏
        if shares > 0 and total_cost > 0:
            mv = shares * nav_val
            pnl = mv - total_cost
            pnl_pct = (pnl / total_cost * 100)
        else:
            mv, pnl, pnl_pct = 0, 0, 0

        # ── 阶梯重置检查 ──
        if pnl_pct < LADDER_RESET * 100 and triggered_levels:
            triggered_levels = set()

        # 更新历史最高浮盈率
        if pnl_pct > peak_pnl_pct:
            peak_pnl_pct = pnl_pct

        # ── 阶梯止盈 ──
        new_triggers = []
        for idx, (th, sr) in enumerate(LADDER):
            if idx not in triggered_levels and pnl_pct >= th * 100:
                triggered_levels.add(idx)
                new_triggers.append(idx)

        for idx_sell in new_triggers:
            sell_sr = LADDER[idx_sell][1]
            sell_shares = shares * sell_sr
            sell_amount = sell_shares * nav_val
            sell_cost_rel = total_cost * sell_sr

            shares -= sell_shares
            total_cost -= sell_cost_rel
            cash += sell_amount

            sell_events.append({
                'date': t,
                'type': f'阶梯+{int(LADDER[idx_sell][0]*100)}%',
                'sell_amount': round(sell_amount, 2),
                'sell_shares': round(sell_shares, 4),
                'nav': nav_val,
            })

            # 重算
            if shares > 0 and total_cost > 0:
                mv = shares * nav_val
                pnl = mv - total_cost
                pnl_pct = (pnl / total_cost * 100)
            else:
                mv, pnl, pnl_pct = 0, 0, 0

            # 阶梯卖出后更新 peak
            if pnl_pct > peak_pnl_pct:
                peak_pnl_pct = pnl_pct

        # ── 移动止盈（仅策略B）──
        if use_trailing and shares > 0 and total_cost > 0 and peak_pnl_pct > 0:
            drawdown_from_peak = peak_pnl_pct - pnl_pct
            if drawdown_from_peak >= TRAILING_TOLERANCE and pnl_pct > 0:
                # 触发移动止盈：卖出 20%
                sell_sr = TRAILING_SELL_RATIO
                sell_shares = shares * sell_sr
                sell_amount = sell_shares * nav_val
                sell_cost_rel = total_cost * sell_sr

                shares -= sell_shares
                total_cost -= sell_cost_rel
                cash += sell_amount

                sell_events.append({
                    'date': t,
                    'type': f'移动止盈(回撤{drawdown_from_peak:.1f}%)',
                    'sell_amount': round(sell_amount, 2),
                    'sell_shares': round(sell_shares, 4),
                    'nav': nav_val,
                })

                # 重算
                if shares > 0 and total_cost > 0:
                    mv = shares * nav_val
                    pnl = mv - total_cost
                    pnl_pct = (pnl / total_cost * 100)
                else:
                    mv, pnl, pnl_pct = 0, 0, 0

                # 移动止盈后重置 peak 为当前盈亏率
                peak_pnl_pct = pnl_pct

        # ── 动态定投买入 ──
        dca_pnl_pct = ((shares * nav_val - total_cost) / total_cost * 100) if total_cost > 0 else 0
        rate = get_dca_deduction_rate(dca_pnl_pct)
        amount = WEEKLY * rate
        bought = (amount / (1 + FEE)) / nav_val
        shares += bought
        total_cost += amount
        total_outflow += amount

        # 买入后重算 peak（成本变了）
        if shares > 0 and total_cost > 0:
            mv = shares * nav_val
            pnl = mv - total_cost
            pnl_pct = (pnl / total_cost * 100)
            if pnl_pct > peak_pnl_pct:
                peak_pnl_pct = pnl_pct
        else:
            mv, pnl, pnl_pct = 0, 0, 0

        avg_cost = total_cost / shares if shares > 0 else 0
        records.append({
            'date': t,
            'nav': nav_val,
            'shares': round(shares, 4),
            'cost': round(total_cost, 2),
            'avg_cost': round(avg_cost, 4),
            'mv': round(mv, 2),
            'cash': round(cash, 2),
            'total_in': round(total_outflow, 2),
            'pnl_pct': round(pnl_pct, 2),
            'peak_pnl': round(peak_pnl_pct, 2),
            'total_assets': round(mv + cash, 2),
        })

    return records, sell_events


def calc_metrics(records, sell_events, label):
    """计算回测指标"""
    df_r = pd.DataFrame(records)
    last = df_r.iloc[-1]

    total_assets = last['total_assets']
    total_in = last['total_in']
    net_pnl = total_assets - total_in
    net_pnl_pct = net_pnl / total_in * 100

    # 最大回撤（基于总资产 = 持仓市值 + 现金）
    df_r['peak'] = df_r['total_assets'].cummax()
    df_r['drawdown'] = (df_r['total_assets'] - df_r['peak']) / df_r['peak'] * 100
    max_drawdown = df_r['drawdown'].min()

    # 最大浮盈
    max_pnl_pct = df_r['pnl_pct'].max()

    # 修复时间：从最大回撤点恢复到创新高的天数
    max_dd_date = df_r.loc[df_r['drawdown'].idxmin(), 'date']
    peak_before_dd = df_r[df_r['date'] <= max_dd_date]['peak'].iloc[-1]
    recovery = df_r[(df_r['date'] > max_dd_date) & (df_r['total_assets'] >= peak_before_dd)]
    if len(recovery) > 0:
        recovery_date = recovery.iloc[0]['date']
        recovery_days = (recovery_date - max_dd_date).days
    else:
        recovery_days = -1  # 未恢复

    # 卖出统计
    n_ladder = len([s for s in sell_events if '阶梯' in s['type']])
    n_trailing = len([s for s in sell_events if '移动' in s['type']])
    total_sell_cash = sum(s['sell_amount'] for s in sell_events)

    print(f"\n{'='*70}")
    print(f"策略{label}: {'阶梯止盈 + 动态定投' if label == 'A' else '阶梯止盈 + 移动止盈(回撤18%) + 动态定投'}")
    print(f"{'='*70}")
    print(f"  回测区间:          {df_r['date'].iloc[0]} ~ {df_r['date'].iloc[-1]}")
    print(f"  定投次数:          {len(df_r)}")
    print(f"  总投入:            ¥{total_in:>12,.2f}")
    print(f"  持仓市值:          ¥{last['mv']:>12,.2f}")
    print(f"  止盈落袋现金:      ¥{last['cash']:>12,.2f}")
    print(f"  总资产:            ¥{total_assets:>12,.2f}")
    print(f"  净盈亏:            ¥{net_pnl:>12,.2f} ({net_pnl_pct:+.2f}%)")
    print(f"  最大浮盈率:        {max_pnl_pct:+.2f}%")
    print(f"  最大回撤(总资产):  {max_drawdown:.2f}%")
    print(f"  最大回撤日期:      {max_dd_date}")
    if recovery_days > 0:
        print(f"  修复时间:          {recovery_days} 天")
    else:
        print(f"  修复时间:          未恢复")
    print(f"  卖出次数:          {len(sell_events)} (阶梯{n_ladder} + 移动{n_trailing})")
    print(f"  卖出总金额:        ¥{total_sell_cash:>12,.2f}")

    if sell_events:
        print(f"\n  卖出明细:")
        for s in sell_events:
            print(f"    {s['date']}  {s['type']:<20s}  卖出¥{s['sell_amount']:>10,.2f}  @¥{s['nav']:.4f}")

    # 打印每年末资产变化
    print(f"\n  每年末资产变化:")
    print(f"  {'年份':6s} {'总投入':>10s} {'持仓市值':>10s} {'现金':>10s} {'总资产':>10s} {'盈亏率':>8s}")
    print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
    df_r['year'] = df_r['date'].apply(lambda x: x.year)
    for yr, grp in df_r.groupby('year'):
        yr_last = grp.iloc[-1]
        yr_pnl = yr_last['total_assets'] - yr_last['total_in']
        yr_pct = yr_pnl / yr_last['total_in'] * 100 if yr_last['total_in'] > 0 else 0
        print(f"  {yr:<6d} ¥{yr_last['total_in']:>9,.0f} ¥{yr_last['mv']:>9,.0f} ¥{yr_last['cash']:>9,.0f} ¥{yr_last['total_assets']:>9,.0f} {yr_pct:>+7.1f}%")

    return {
        'label': label,
        'net_pnl': net_pnl,
        'net_pnl_pct': net_pnl_pct,
        'max_drawdown': max_drawdown,
        'max_pnl_pct': max_pnl_pct,
        'recovery_days': recovery_days,
        'n_sells': len(sell_events),
        'total_sell_cash': total_sell_cash,
        'total_assets': total_assets,
    }


# ── 运行两个策略 ──────────────────────────────────────────
print("\n" + "=" * 70)
print("开始回测富国新机遇(004674) 策略对比")
print("=" * 70)

records_a, sells_a = run_backtest(use_trailing=False)
metrics_a = calc_metrics(records_a, sells_a, "A")

records_b, sells_b = run_backtest(use_trailing=True)
metrics_b = calc_metrics(records_b, sells_b, "B")

# ── 对比汇总 ──────────────────────────────────────────────
ma, mb = metrics_a, metrics_b
print(f"\n\n{'='*70}")
print("对比汇总")
print(f"{'='*70}")
print(f"{'指标':<20s} {'策略A(纯阶梯)':>18s} {'策略B(阶梯+移动)':>18s} {'差异':>14s}")
print(f"{'─'*20} {'─'*18} {'─'*18} {'─'*14}")
print(f"{'净盈亏':<20s} {'¥'+format(ma['net_pnl'], ',.2f'):>18s} {'¥'+format(mb['net_pnl'], ',.2f'):>18s} {'¥'+format(mb['net_pnl']-ma['net_pnl'], ',.2f'):>14s}")
print(f"{'收益率':<20s} {ma['net_pnl_pct']:+.2f}%".rjust(38) + f" {mb['net_pnl_pct']:+.2f}%".rjust(18) + f" {mb['net_pnl_pct']-ma['net_pnl_pct']:+.2f}%".rjust(14))
print(f"{'最大回撤':<20s} {ma['max_drawdown']:.2f}%".rjust(38) + f" {mb['max_drawdown']:.2f}%".rjust(18) + f" {mb['max_drawdown']-ma['max_drawdown']:.2f}%".rjust(14))
print(f"{'最大浮盈率':<20s} {ma['max_pnl_pct']:+.2f}%".rjust(38) + f" {mb['max_pnl_pct']:+.2f}%".rjust(18) + f" {mb['max_pnl_pct']-ma['max_pnl_pct']:+.2f}%".rjust(14))
ra = ma['recovery_days']
rb = mb['recovery_days']
ra_str = f"{ra}天" if ra > 0 else "未恢复"
rb_str = f"{rb}天" if rb > 0 else "未恢复"
print(f"{'修复时间':<20s} {ra_str:>18s} {rb_str:>18s}")
print(f"{'卖出次数':<20s} {ma['n_sells']:>18d} {mb['n_sells']:>18d} {mb['n_sells']-ma['n_sells']:>14d}")
print(f"{'卖出总金额':<20s} {'¥'+format(ma['total_sell_cash'], ',.0f'):>18s} {'¥'+format(mb['total_sell_cash'], ',.0f'):>18s} {'¥'+format(mb['total_sell_cash']-ma['total_sell_cash'], ',.0f'):>14s}")
print(f"{'最终总资产':<20s} {'¥'+format(ma['total_assets'], ',.2f'):>18s} {'¥'+format(mb['total_assets'], ',.2f'):>18s} {'¥'+format(mb['total_assets']-ma['total_assets'], ',.2f'):>14s}")
