"""
富国新机遇灵活配置混合A (004674) 回测
策略：月定投 + 止盈/止损 + 移动止盈
"""

import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta


def fetch_full_history(fund_code: str) -> pd.DataFrame:
    """从 AkShare 拉取完整的净值历史"""
    df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    df_accum = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")

    date_col = "净值日期" if "净值日期" in df_unit.columns else df_unit.columns[0]
    df_unit = df_unit.rename(columns={date_col: "date", "单位净值": "unit_nav"})
    df_accum = df_accum.rename(columns={date_col: "date", "累计净值": "accum_nav"})

    df = pd.merge(df_unit[["date", "unit_nav"]], df_accum[["date", "accum_nav"]], on="date", how="left")
    df["date"] = pd.to_datetime(df["date"])
    df["accum_nav"] = df["accum_nav"].astype(float)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _partial_sell(total_shares, total_cost, nav, sell_ratio):
    """部分卖出：卖出 sell_ratio 比例的份额，剩余持仓按比例缩减成本"""
    sell_shares = total_shares * sell_ratio
    cash_out = sell_shares * nav
    remaining_shares = total_shares - sell_shares
    remaining_cost = total_cost * (1 - sell_ratio)
    return remaining_shares, remaining_cost, cash_out


def _calc_xirr(cash_flows, final_value, end_date):
    """计算 XIRR 年化收益率（牛顿法逼近）

    cash_flows: [(date, amount)], 负=投入, 正=取出
    final_value: 期末总资产（视为最后一笔正现金流）
    """
    if not cash_flows:
        return None
    # 最后一笔：期末全部变现
    flows = cash_flows + [(end_date, final_value)]
    # 统一用年份差
    dates = [d for d, _ in flows]
    amounts = [a for d, a in flows]
    d0 = dates[0]

    def npv(rate):
        total = 0.0
        for d, amt in zip(dates, amounts):
            years = (d - d0).days / 365.25
            total += amt / ((1 + rate) ** years)
        return total

    # 牛顿法求解
    r = 0.05
    for _ in range(100):
        f = npv(r)
        if abs(f) < 0.01:
            return r
        df = (npv(r + 0.0001) - f) / 0.0001
        if abs(df) < 1e-10:
            break
        r = r - f / df
    return None if r < -0.99 else r


def run_backtest(
    df: pd.DataFrame,
    fund_name: str,
    monthly_amount: float = 1000.0,
    stop_profit: float = 0.25,
    stop_loss: float = -0.15,
    trailing_start: float = 0.30,
    trailing_tolerance: float = 0.12,
    sell_ratio: float = 0.33,        # 每次触发卖出 1/3
    cap_amount: float = 0.0,         # 市值上限：盈利时总资产超过此值则卖出超额部分；0=不启用
    profit_cap_amount: float = 0.0,  # 利润帽：浮动利润超过此金额时卖出利润部分；0=不启用
):
    """回测引擎 — 所有触发均「部分卖出」，定投持续不变

    - sell_ratio: 统一的部分卖出比例（止盈/止损/移动止盈均适用）
    - cap_amount:  市值上限止盈（超过时卖出超额部分）
    """
    total_shares = 0.0
    total_cost = 0.0
    total_invested = 0.0
    cash_pool = 0.0
    peak_profit = 0.0
    trailing_active = False
    last_invest_month = None

    trades = []
    cash_flows = []
    profit_sells = 0
    stop_loss_sells = 0
    trailing_sells = 0
    cap_sells = 0
    profit_cap_sells = 0
    max_drawdown = 0.0
    peak_assets = 0.0
    fund_peak_nav = 0.0
    fund_max_dd = 0.0

    for idx, row in df.iterrows():
        current_date = row["date"].date()
        nav = row["accum_nav"]

        # ── 月定投 ──
        ym = (current_date.year, current_date.month)
        if ym != last_invest_month:
            shares = monthly_amount / nav
            total_shares += shares
            total_cost += monthly_amount
            total_invested += monthly_amount
            last_invest_month = ym
            cash_flows.append((current_date, -monthly_amount))  # 支出

        if total_shares <= 0:
            continue

        mv = total_shares * nav
        current_assets = mv + cash_pool   # 策略当前总资产

        # 策略最大回撤
        if current_assets > peak_assets:
            peak_assets = current_assets
        dd = (current_assets - peak_assets) / peak_assets if peak_assets > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd

        # 基金净值最大回撤（买入持有 = 等于基金的净值回撤）
        if nav > fund_peak_nav:
            fund_peak_nav = nav
        fund_dd = (nav - fund_peak_nav) / fund_peak_nav if fund_peak_nav > 0 else 0
        if fund_dd < fund_max_dd:
            fund_max_dd = fund_dd

        profit = mv - total_cost
        profit_pct = profit / total_cost if total_cost > 0 else 0

        # 更新最高利润率
        if profit_pct > peak_profit:
            peak_profit = profit_pct

        # 移动止盈激活
        if profit_pct >= trailing_start and not trailing_active:
            trailing_active = True
            peak_profit = profit_pct

        # ── 1. 静态止盈 → 卖出 1/3 ──
        if stop_profit and profit_pct >= stop_profit:
            total_shares, total_cost, cash = _partial_sell(total_shares, total_cost, nav, sell_ratio)
            # 重置剩余持仓成本为当前市值 —— 避免次日重复触发
            total_cost = total_shares * nav
            cash_pool += cash
            cash_flows.append((current_date, cash))  # 现金流入
            peak_profit = 0.0
            trailing_active = False
            profit_sells += 1
            trades.append({
                "date": current_date, "type": f"止盈卖出{int(sell_ratio*100)}%", "nav": nav,
                "profit_pct": profit_pct * 100, "cash_out": cash,
            })
            continue

        # ── 2. 止损 → 卖出 1/3（不清仓）──
        if stop_loss and profit_pct <= stop_loss:
            total_shares, total_cost, cash = _partial_sell(total_shares, total_cost, nav, sell_ratio)
            # 重置成本：卖出后剩余持仓以当前市值重新计价
            total_cost = total_shares * nav
            cash_pool += cash
            cash_flows.append((current_date, cash))
            stop_loss_sells += 1
            trades.append({
                "date": current_date, "type": f"止损卖出{int(sell_ratio*100)}%", "nav": nav,
                "profit_pct": profit_pct * 100, "cash_out": cash,
            })
            continue

        # ── 3. 移动止盈 → 卖出 1/3 ──
        if trailing_active and trailing_tolerance:
            drawdown_from_peak = profit_pct - peak_profit
            if drawdown_from_peak <= -trailing_tolerance:
                total_shares, total_cost, cash = _partial_sell(total_shares, total_cost, nav, sell_ratio)
                total_cost = total_shares * nav
                cash_pool += cash
                cash_flows.append((current_date, cash))
                trailing_active = False
                peak_profit = 0.0
                trailing_sells += 1
                trades.append({
                    "date": current_date, "type": f"移动止盈卖出{int(sell_ratio*100)}%",
                    "nav": nav, "profit_pct": profit_pct * 100,
                    "peak_pct": peak_profit * 100, "cash_out": cash,
                })
                continue

        # ── 4. 市值上限止盈：总资产超过上限时，卖出超额部分 ──
        if cap_amount > 0 and current_assets > cap_amount and profit_pct > 0:
            # 只从市值部分卖出，现金不动。目标：mv + cash_pool ≤ cap_amount
            target_mv = max(0, cap_amount - cash_pool)
            excess_mv = mv - target_mv
            if excess_mv > 0:
                # 门槛：超出部分不到 ¥200 或不到上限的 1%，不卖（避免频繁微调）
                min_excess = max(200.0, cap_amount * 0.01)
                if excess_mv < min_excess:
                    pass  # 不触发
                else:
                    sell_shares = min((excess_mv / mv) * total_shares, total_shares)
                    sell_shares = max(sell_shares, 0)
                    if sell_shares > 0:
                        cash = sell_shares * nav
                        total_shares -= sell_shares
                        # 重置成本（只重置卖出的部分比例）
                        total_cost = total_shares * nav
                        cash_pool += cash
                        cash_flows.append((current_date, cash))
                        cap_sells += 1
                        trades.append({
                            "date": current_date, "type": f"市值上限卖出(>¥{cap_amount/10000:.0f}万)",
                            "nav": nav, "profit_pct": profit_pct * 100, "cash_out": cash,
                        })
                        continue

        # ── 5. 利润帽：浮动利润超过阈值时，只卖利润，本金不动 ──
        if profit_cap_amount > 0 and profit > profit_cap_amount:
            # 只卖出超额利润部分，不卖本金
            sell_shares = (profit / mv) * total_shares
            sell_shares = min(sell_shares, total_shares)
            if sell_shares > 0:
                cash = sell_shares * nav
                # 验证：卖出金额应接近利润
                if cash >= profit_cap_amount * 0.5:  # 门槛：至少卖出一半利润帽金额
                    total_shares -= sell_shares
                    total_cost = total_shares * nav   # 本金成本重置，利润归零
                    cash_pool += cash
                    cash_flows.append((current_date, cash))
                    profit_cap_sells += 1
                    trades.append({
                        "date": current_date, "type": f"利润帽卖出(盈利>{profit_cap_amount/10000:.1f}万)",
                        "nav": nav, "profit_pct": profit_pct * 100, "cash_out": cash,
                    })
                    continue

    # ── 最终结果 ──
    final_nav = df.iloc[-1]["accum_nav"]
    final_mv = total_shares * final_nav
    total_assets = cash_pool + final_mv
    total_return = total_assets - total_invested
    total_return_pct = (total_return / total_invested * 100) if total_invested > 0 else 0

    # 买入持有对照
    buy_hold_shares = total_invested / df.iloc[0]["accum_nav"] if len(df) > 0 else 0
    buy_hold_mv = buy_hold_shares * final_nav
    buy_hold_return = buy_hold_mv - total_invested
    buy_hold_pct = (buy_hold_return / total_invested * 100) if total_invested > 0 else 0

    print("=" * 70)
    print(f"  基金: {fund_name}")
    print(f"  区间: {df.iloc[0]['date'].date()} → {df.iloc[-1]['date'].date()} ({len(df)} 个交易日)")
    print("=" * 70)
    print(f"  每月定投: ¥{monthly_amount:,.0f}")
    print(f"  累计投入: ¥{total_invested:,.2f}  (共 {last_invest_month[0]-df.iloc[0]['date'].year + 1 if last_invest_month else 0} 年)")
    print()
    print(f"  ── 策略结果 ──")
    print(f"  期末持仓市值: ¥{final_mv:,.2f}")
    print(f"  已落袋现金:   ¥{cash_pool:,.2f}")
    print(f"  总资产:       ¥{total_assets:,.2f}")
    print(f"  总收益:       ¥{total_return:,.2f}  ({total_return_pct:+.2f}%)")
    print(f"  最大回撤:     {max_drawdown*100:+.2f}%")
    # XIRR 年化收益率
    xirr = _calc_xirr(cash_flows, final_mv, df.iloc[-1]["date"].date())
    if xirr is not None:
        print(f"  XIRR 年化:    {xirr*100:+.2f}%")
    print()
    print(f"  ── 买入持有对照 ──")
    print(f"  买入持有市值: ¥{buy_hold_mv:,.2f}")
    print(f"  买入持有收益: ¥{buy_hold_return:,.2f}  ({buy_hold_pct:+.2f}%)")
    print(f"  买入持有最大回撤: {fund_max_dd*100:+.2f}%")
    # 买入持有年化
    bh_years = (df.iloc[-1]["date"].date() - df.iloc[0]["date"].date()).days / 365.25
    bh_annual = (buy_hold_mv / total_invested) ** (1 / bh_years) - 1 if bh_years > 0 and total_invested > 0 else 0
    print(f"  买入持有年化: {bh_annual*100:+.2f}%")
    print(f"  策略超额:     {total_return_pct - buy_hold_pct:+.2f}%")
    print()
    print(f"  ── 风控触发记录 ──")
    print(f"  止盈卖出: {profit_sells} 次")
    print(f"  止损卖出: {stop_loss_sells} 次")
    print(f"  移动止盈: {trailing_sells} 次")
    print(f"  市值上限: {cap_sells} 次")
    print(f"  利润帽:   {profit_cap_sells} 次")
    if trades:
        for t in trades:
            print(f"    {t['date']} [{t['type']}] 收益 {t['profit_pct']:+.2f}%, 落袋 ¥{t['cash_out']:,.2f}")
    else:
        print("    (无触发)")
    print()


# ═══════════════════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    FUND_CODE = "004674"
    FUND_NAME = "富国新机遇灵活配置混合A"

    print("正在从 AkShare 拉取历史净值数据...")
    df_full = fetch_full_history(FUND_CODE)
    print(f"数据范围: {df_full.iloc[0]['date'].date()} → {df_full.iloc[-1]['date'].date()} ({len(df_full)} 行)")

    # 风控参数
    params = {
        "stop_profit": 0.25,
        "stop_loss": -0.15,
        "trailing_start": 0.30,
        "trailing_tolerance": 0.12,
    }

    print(f"\n📋 风控参数: 止盈{params['stop_profit']*100:.0f}% | 止损{params['stop_loss']*100:.0f}% | 移动止盈起点{params['trailing_start']*100:.0f}% | 容忍回撤{params['trailing_tolerance']*100:.0f}%")

    # ── 回测1: 旧版 DCA ¥1000, 无市值上限 ──
    print("\n" + "🔵" * 35)
    print("  方案 A: 月定投 ¥1,000 — 无市值上限 (你的旧策略)")
    print("🔵" * 35)
    run_backtest(df_full, FUND_NAME, monthly_amount=1000.0, **params)

    # ── 回测2: 新版 DCA ¥500, 市值上限 ¥20,000 ──
    print("\n" + "🟢" * 35)
    print("  方案 B: 月定投 ¥500 — 市值上限 ¥20,000 (盈利时超出的卖掉)")
    print("🟢" * 35)
    run_backtest(df_full, FUND_NAME, **params, monthly_amount=500.0, cap_amount=20000.0)

    # ── 近三年对比 ──
    three_years_ago = datetime.now() - timedelta(days=365 * 3)
    df_3y = df_full[df_full["date"] >= pd.Timestamp(three_years_ago)].reset_index(drop=True)

    if len(df_3y) > 0:
        print("\n" + "�" * 35)
        print("  方案 A 近三年: 月定投 ¥1,000 — 无上限")
        print("�" * 35)
        run_backtest(df_3y, FUND_NAME, monthly_amount=1000.0, **params)

        print("\n" + "🟢" * 35)
        print("  方案 B 近三年: 月定投 ¥500 — ¥20,000 上限")
        print("🟢" * 35)
        run_backtest(df_3y, FUND_NAME, **params, monthly_amount=500.0, cap_amount=20000.0)
