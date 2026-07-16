import pandas as pd
import os
from datetime import datetime, timedelta

LADDER = [(0.15, 0.5), (0.25, 0.5), (0.35, 0.5), (0.50, 0.5)]
DD_THRESH = 0.25
DD_SELL_PCT = 0.5
INVEST_DAY = 3
INVEST_AMT = 150

def get_data(code, start, end):
    cache = f'/home/tianp/projects/MyFund-Quant-System/data/{code}_history_v2.csv'
    df = pd.read_csv(cache)
    df['净值日期'] = pd.to_datetime(df['净值日期'])
    df = df[(df['净值日期'] >= start) & (df['净值日期'] <= end)].dropna(subset=['单位净值'])
    df['单位净值'] = pd.to_numeric(df['单位净值'])
    df = df.sort_values('净值日期').reset_index(drop=True)
    df['peak_nav'] = df['单位净值'].cummax()
    df['dd'] = (df['单位净值'] - df['peak_nav']) / df['peak_nav']
    return df

def backtest(code, name, start, end, sell_on_loss):
    df = get_data(code, start, end)
    shares = cost = invested = cash = 0.0
    last_period = None
    ladder = 0
    trades = []
    for _, row in df.iterrows():
        dt, nav, dd = row['净值日期'], row['单位净值'], row['dd']
        period = (dt.isocalendar()[0], dt.isocalendar()[1])
        if period != last_period and (dt.weekday() + 1) >= INVEST_DAY:
            buy_shares = INVEST_AMT / nav
            shares += buy_shares
            cost += INVEST_AMT
            invested += INVEST_AMT
            last_period = period
            trades.append(('BUY', dt.strftime('%Y-%m-%d'), nav, INVEST_AMT))
        mv = shares * nav
        pct = (mv - cost) / cost if cost > 0 else 0
        sell = False
        reason = ''
        for i, (tp, sp) in enumerate(LADDER):
            if i >= ladder and pct >= tp:
                sell = True
                reason = 'LADDER' + str(int(tp*100))
                ladder = i + 1
                break
        if not sell and dd <= -DD_THRESH and shares > 0:
            if sell_on_loss or pct > 0:
                sell = True
                reason = 'DD' + str(int(DD_THRESH*100)) + ('_PROFIT' if not sell_on_loss else '')
        if sell:
            s_shares = shares * DD_SELL_PCT
            cash += s_shares * nav
            shares -= s_shares
            cost = shares * nav
            trades.append(('SELL', dt.strftime('%Y-%m-%d'), nav, round(s_shares * nav, 2), reason))
    final_mv = shares * df.iloc[-1]['单位净值']
    profit = (cash + final_mv) - invested
    ret = profit / invested * 100 if invested > 0 else 0
    return {'code': code, 'name': name, 'invested': round(invested, 0), 'cash': round(cash, 0), 'mv': round(final_mv, 0), 'profit': round(profit, 0), 'ret': round(ret, 2), 'trades': trades}

today = datetime.today()
start = (today - timedelta(days=365*5)).strftime('%Y-%m-%d')
end = today.strftime('%Y-%m-%d')
funds = [('008903', '广发科技先锋'), ('004674', '富国新机遇')]
strats = [('ALL', True), ('PROFIT_ONLY', False)]

print('='*100)
print('回测结果对比报告 - 阶段止盈+回撤25%减仓策略')
print('='*100)
print('基金 | 策略 | 投入 | 现金 | 市值 | 收益 | 收益率 | 买卖次数')
print('-'*100)

for code, name in funds:
    for s_name, sell_loss in strats:
        r = backtest(code, name, start, end, sell_loss)
        buys = sum(1 for t in r['trades'] if t[0] == 'BUY')
        sells = sum(1 for t in r['trades'] if t[0] == 'SELL')
        p_sign = '+' if r['profit'] >= 0 else ''
        print(name + '|' + s_name + '|' + str(int(r['invested'])) + '|' + str(int(r['cash'])) + '|' + str(int(r['mv'])) + '|' + p_sign + str(int(r['profit'])) + '|' + str(r['ret']) + '%|' + str(buys) + '/' + str(sells))

print('\n' + '='*100)
print('详细交易记录')
print('='*100)

for code, name in funds:
    print('\n---', name, code, '---')
    for s_name, sell_loss in strats:
        r = backtest(code, name, start, end, sell_loss)
        print('\n策略:', s_name)
        for t in r['trades']:
            print(' ', t[1], t[0], '净值=', t[2], '金额=', t[3], ('原因='+t[4] if len(t)>4 else ''))