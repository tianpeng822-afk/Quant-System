"""批量回测 — 阶梯止盈 + 慧定投"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime


def get_dca_multiplier(pnl_pct: float) -> float:
    """慧定投扣款倍率 (来自 pipeline.py)"""
    if pnl_pct >= 25:   return 0.50
    if pnl_pct >= 20:   return 0.525
    if pnl_pct >= 15:   return 0.55
    if pnl_pct >= 10:   return 0.60
    if pnl_pct >= 7.5:  return 0.70
    if pnl_pct >= 5:    return 0.80
    if pnl_pct >= 2.5:  return 0.90
    if pnl_pct >= -2.5: return 1.00
    if pnl_pct >= -5:   return 1.20
    if pnl_pct >= -7.5: return 1.40
    if pnl_pct >= -10:  return 1.60
    if pnl_pct >= -15:  return 1.80
    if pnl_pct >= -20:  return 1.90
    if pnl_pct >= -25:  return 1.95
    return 2.00


# 阶梯止盈: (浮盈阈值, 卖出比例)
LEVELS = [
    (0.25, 0.20),  # +25% → 卖 20%
    (0.40, 0.20),  # +40% → 卖 20%
    (0.60, 0.20),  # +60% → 卖 20%
    (0.95, 0.15),  # +95% → 卖 15%
    (1.50, 0.25),  # +150% → 卖 25%
]
RESET_BELOW = 0.05   # 浮盈跌回 5% 以下重置阶梯


def fetch_data(code):
    """拉取净值历史"""
    df_unit = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    df_accum = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
    date_col = "净值日期" if "净值日期" in df_unit.columns else df_unit.columns[0]
    df_unit = df_unit.rename(columns={date_col: "date", "单位净值": "unit_nav"})
    df_accum = df_accum.rename(columns={date_col: "date", "累计净值": "accum_nav"})
    df = pd.merge(df_unit[["date", "unit_nav"]], df_accum[["date", "accum_nav"]], on="date", how="left")
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = df["unit_nav"].astype(float)
    df["accum_nav"] = df["accum_nav"].astype(float)
    return df.sort_values("date").reset_index(drop=True)


def run(df, monthly):
    """回测: 阶梯止盈 + 慧定投"""
    shares = 0.0
    cost = 0.0          # 持仓成本（卖出时按比例缩减）
    invested = 0.0      # 累计投入（现金口径）
    cash_pool = 0.0     # 已落袋现金

    next_level = 0      # 当前等待触发的阶梯层级
    last_month = None

    peak_assets = 0.0
    max_dd = 0.0

    total_sells = 0
    dca_adjusts = 0     # 慧定投调整次数

    cash_flows = []     # 现金流 (date, amount)  负=投入, 正=取出

    for _, row in df.iterrows():
        d = row["date"].date()
        nav = float(row["accum_nav"])

        # ---- 每月定投 ----
        ym = (d.year, d.month)
        if ym != last_month:
            pnl_pct = (shares * nav - cost) / cost * 100 if cost > 0 else 0
            mult = get_dca_multiplier(pnl_pct)
            if abs(mult - 1.0) > 0.01:
                dca_adjusts += 1
            amt = monthly * mult
            shares += amt / nav
            cost += amt               # 成本按实际投入累加
            invested += amt
            last_month = ym
            cash_flows.append((d, -amt))

            # 阶梯重置检查（只在定投日检查，避免盘中波动误触发）
            if cost > 0:
                pp = (shares * nav - cost) / cost
                if pp < RESET_BELOW:
                    next_level = 0

        if shares <= 0:
            continue

        # ---- 资产统计 ----
        mv = shares * nav
        assets = mv + cash_pool
        if assets > peak_assets:
            peak_assets = assets
        dd = (assets - peak_assets) / peak_assets if peak_assets > 0 else 0
        if dd < max_dd:
            max_dd = dd

        # ---- 阶梯止盈 ----
        pp = (mv - cost) / cost if cost > 0 else 0

        while next_level < len(LEVELS) and pp >= LEVELS[next_level][0] and shares > 0:
            threshold, sell_ratio = LEVELS[next_level]
            out = shares * sell_ratio * nav      # 卖出金额
            shares *= (1 - sell_ratio)            # 份额按比例减少
            cost *= (1 - sell_ratio)              # 成本按比例减少（不重置为市值）
            cash_pool += out
            cash_flows.append((d, out))
            next_level += 1
            total_sells += 1

            # 更新浮盈率
            mv = shares * nav
            pp = (mv - cost) / cost if cost > 0 else 0

    # ---- 期末结算 ----
    final_nav = df.iloc[-1]["accum_nav"]
    final_mv = float(shares * final_nav)
    total_assets = cash_pool + final_mv

    return {
        "invested": invested,
        "final_mv": final_mv,
        "cash": cash_pool,
        "total_assets": total_assets,
        "max_dd": max_dd,
        "sells": total_sells,
        "dca_adjusts": dca_adjusts,
    }


# ═══════════════════════════════════════════════════════════
# 基金配置: (代码, 名称, 月投金额)
# ═══════════════════════════════════════════════════════════
configs = [
    ("004674", "富国新机遇", 150),
    ("008903", "广发科技",   150),
    ("163406", "兴全合润",   150),
    ("001618", "天虹电子",   600),
    ("019034", "易方达高端", 400),
]

print()
print("=" * 120)
print(f"  策略: 阶梯止盈({'/'.join(f'{int(t[0]*100)}%卖{int(t[1]*100)}%' for t in LEVELS)}) + 慧定投(盈亏率动态 0.50x~2.00x)")
print(f"  成本: 卖出按比例缩减 | 重置: 浮盈 < {RESET_BELOW*100:.0f}% | 止损: 无 | 回购: 无")
print("=" * 120)
print(f'  {"基金":<10s} {"代码":>7s}  {"定投":>5s} | {"投入":>9s}  {"总资产":>10s}  {"收益率":>8s}  {"持仓":>9s}  {"现金":>9s}  {"最大回撤":>8s}  {"卖出":>4s}  {"慧":>3s}')
print("-" * 120)

for code, name, monthly in configs:
    print(f"  拉取 {name}({code})...", end=" ", flush=True)
    df = fetch_data(code)
    info = f"{df.iloc[0]['date'].date()} → {df.iloc[-1]['date'].date()}"
    print(info)

    r = run(df, monthly)
    ret_pct = (r["total_assets"] - r["invested"]) / r["invested"] * 100

    print(f'  {name:<10s} {code:>7s}  ¥{monthly:>4,.0f} | '
          f'¥{r["invested"]:>8,.0f}  ¥{r["total_assets"]:>9,.0f}  '
          f'{ret_pct:>+7.2f}%  ¥{r["final_mv"]:>8,.0f}  ¥{r["cash"]:>8,.0f}  '
          f'{r["max_dd"]*100:>+7.2f}%  {r["sells"]:>4d}  {r["dca_adjusts"]:>3d}')

print()
