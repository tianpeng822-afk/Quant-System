"""批量回测所有持仓基金"""
import io, sys, os, contextlib

sys.path.insert(0, os.path.dirname(__file__))

import backtest_004674 as bt
from backtest_004674 import fetch_full_history

_original = bt.run_backtest

def quick_backtest(df, fund_name, monthly_amount, stop_profit, stop_loss,
                   trailing_start, trailing_tolerance, cap_amount=0, profit_cap_amount=0):
    """Capture key metrics from backtest output"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _original(df, fund_name, monthly_amount, stop_profit, stop_loss,
                  trailing_start, trailing_tolerance, cap_amount, profit_cap_amount)
    out = buf.getvalue()
    result = {}
    for line in out.split('\n'):
        line = line.strip()
        if '累计投入:' in line:
            try:
                result['invested'] = float(line.split('¥')[1].split()[0].replace(',', ''))
            except:
                pass
        if '总资产:' in line:
            try:
                result['total'] = float(line.split('¥')[1].split()[0].replace(',', ''))
            except:
                pass
        if '总收益:' in line:
            parts = line.split('(')
            if len(parts) > 1:
                pct_str = parts[1].replace('%)','').replace('%','').replace('+','').strip()
                try:
                    result['return_pct'] = float(pct_str)
                except:
                    pass
        if '最大回撤:' in line and '策略' not in line and '买入' not in line:
            try:
                result['dd'] = float(line.split(':')[1].replace('%','').strip())
            except:
                pass
        if 'XIRR 年化' in line:
            try:
                result['xirr'] = float(line.split('+')[1].replace('%','').strip())
            except:
                pass
        if '止盈卖出:' in line:
            try:
                result['profit_sell'] = int(line.split(':')[1].split('次')[0].strip())
            except:
                pass
        if '止损卖出:' in line:
            try:
                result['loss_sell'] = int(line.split(':')[1].split('次')[0].strip())
            except:
                pass
        if '移动止盈:' in line:
            try:
                result['trail_sell'] = int(line.split(':')[1].split('次')[0].strip())
            except:
                pass
        if '利润帽:' in line:
            try:
                result['cap_sell'] = int(line.split(':')[1].split('次')[0].strip())
            except:
                pass
    return result


# All configs: (code, name, monthly, stop_profit, stop_loss, trailing_start, trailing_tolerance, profit_cap)
configs = [
    # 富国新机遇
    ("004674", "富国新机遇",           150, 0.25, -0.15, 0.30, 0.12, 0),
    ("004674", "富国新机遇 +利润帽500", 150, 0.25, -0.15, 0.30, 0.12, 500),
    # 广发科技
    ("008903", "广发科技",             150, 0.25, -0.25, 0.50, 0.18, 0),
    ("008903", "广发科技 +利润帽800",   150, 0.25, -0.25, 0.50, 0.18, 800),
    # 兴全合润
    ("163406", "兴全合润",             150, 0.25, -0.20, 0.60, 0.13, 0),
    ("163406", "兴全合润 +利润帽600",   150, 0.25, -0.20, 0.60, 0.13, 600),
    # 天虹电子
    ("001618", "天虹电子",             600, 0.25, -0.12, 0.20, 0.10, 0),
    ("001618", "天虹电子 +利润帽300",   600, 0.25, -0.12, 0.20, 0.10, 300),
    # 易方达高端
    ("019034", "易方达高端",           400, 0.25, -0.20, 0.20, 0.08, 0),
    ("019034", "易方达高端 +利润帽300", 400, 0.25, -0.20, 0.20, 0.08, 300),
]

last_code = None
for code, name, mo, sp, sl, ts, tt, pc in configs:
    if code != last_code:
        base = name.split('+')[0].strip()
        print(f'\n{"="*95}')
        print(f'  {base} ({code})  月投¥{mo}  止盈{sp*100:.0f}%  止损{sl*100:+.0f}%  移动{ts*100:.0f}%  容忍{tt*100:.0f}%')
        print(f'{"-"*95}')
        last_code = code

    label = name.split('+')[-1].strip() if '+' in name else '无利润帽'
    df = fetch_full_history(code)
    res = quick_backtest(df, '', mo, sp, sl, ts, tt, 0, pc)

    i = res.get('invested') or 0
    t = res.get('total') or 0
    r = res.get('return_pct') or 0
    x = res.get('xirr') or 0
    d = res.get('dd') or 0
    ps = res.get('profit_sell') or 0
    ls = res.get('loss_sell') or 0
    ts_s = res.get('trail_sell') or 0
    cs = res.get('cap_sell') or 0

    print(f'  [{label:14s}] ¥{i:>9,.0f} -> ¥{t:>9,.0f}  '
          f'收益{r:>+7.1f}%  XIRR{x:>+7.1f}%  DD{d:>+7.2f}%  止盈{ps}  止损{ls}  移{ts_s}  帽{cs}')
    if pc > 0:
        print(f'    DEBUG: res keys={list(res.keys())[:10]} i={i} t={t}')

print()
