"""阶梯止盈监控 — 每日检查触发状态，建议操作"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import akshare as ak
import sqlite3
from datetime import date


LEVELS = [(0.20, 0.20), (0.35, 0.20), (0.50, 0.20), (0.65, 0.30)]
STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'ladder_state.json')


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def fetch_nav(code):
    df = ak.fund_open_fund_info_em(symbol=code, indicator='单位净值走势')
    dc = '净值日期' if '净值日期' in df.columns else df.columns[0]
    latest = df.sort_values(dc).iloc[-1]
    return float(latest['单位净值']), latest[dc]


def main():
    db = sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'data', 'myfund.db'))
    db.row_factory = sqlite3.Row
    
    state = load_state()
    monitor_codes = ['004674', '008903', '163406', '001618', '019034']
    alerts = []
    
    print(f"阶梯止盈监控 — {date.today()}")
    print("=" * 80)

    for code in monitor_codes:
        h = db.execute('SELECT * FROM holdings WHERE fund_code=?', (code,)).fetchone()
        if not h or float(h['shares']) <= 0:
            continue

        name = h['fund_name']
        shares = float(h['shares'])
        cost = float(h['total_cost'])
        avg = cost / shares if shares > 0 else 0
        
        # 获取最新净值
        try:
            nav, nav_date = fetch_nav(code)
        except Exception as e:
            print(f'  [{code}] {name}: 获取净值失败 ({e})')
            continue

        mv = shares * nav
        pp = (mv - cost) / cost * 100 if cost > 0 else 0

        # 读取之前的阶梯状态，初始化
        if code not in state:
            state[code] = {'triggered': [], 'last_reset': None, 'peak_nav': 0}

        st = state[code]
        
        # 检查重置
        if pp < 5:
            if st['triggered']:
                st['triggered'] = []
                st['last_reset'] = str(date.today())
                print(f'  [{code}] {name}: 🔄 浮盈{pp:+.1f}% < 5%, 阶梯已重置!')

        # 检查是否有新层级触发
        triggered = st['triggered'].copy()
        new_triggers = []
        
        for idx, (th, sr) in enumerate(LEVELS):
            if idx not in triggered and pp >= th * 100:
                triggered.append(idx)
                new_triggers.append(idx)

        if new_triggers:
            # 累积计算卖出 (逐层)
            remaining_sr = 1.0
            total_out = 0.0
            for idx_sell in new_triggers:
                sr = LEVELS[idx_sell][1]
                sell_shares = shares * remaining_sr * sr
                sell_amount = sell_shares * nav
                remaining_sr *= (1 - sr)
                total_out += sell_amount
            
            st['triggered'] = triggered
            
            alert = {
                'code': code, 'name': name,
                'new_triggers': [int(LEVELS[i][0]*100) for i in new_triggers],
                'nav': nav, 'pp': pp, 'mv': mv,
                'shares': shares, 'sell_amount': round(total_out, 2),
                'sell_shares': round(shares * (1 - remaining_sr), 2),
                'date': str(date.today()),
            }
            alerts.append(alert)
        
        # 更新 peak_nav
        if nav > st.get('peak_nav', 0):
            st['peak_nav'] = nav
        
        # 打印状态
        marks = ' '.join(['✅' if i in triggered else '◻' for i in range(len(LEVELS))])
        if new_triggers:
            triggered_pct = [f"+{LEVELS[i][0]*100:.0f}%" for i in new_triggers]
            print(f'  [{code}] {name}: {marks}')
            print(f'    🔔 新触发! {", ".join(triggered_pct)}档  |  浮盈 {pp:+.2f}%  |  NAV ¥{nav:.4f}')
            print(f'    建议卖出: ¥{total_out:,.2f} ({shares * (1 - remaining_sr):,.2f}份)')
        else:
            next_level_idx = len(triggered)
            if next_level_idx < len(LEVELS):
                next_th = LEVELS[next_level_idx][0]
                target_nav = avg * (1 + next_th)
                gap = (next_th * 100 - pp)
                print(f'  [{code}] {name}: {marks}  |  浮盈 {pp:+.2f}%  |  下一档+{next_th*100:.0f}%差{gap:.1f}%  |  NAV ¥{nav:.4f}')
            else:
                print(f'  [{code}] {name}: {marks}  |  浮盈 {pp:+.2f}%  |  全部触发, 等重置(<5%)  |  NAV ¥{nav:.4f}')

    # 保存状态
    save_state(state)

    # 汇总告警
    if alerts:
        print()
        print("=" * 80)
        print("⚠️  需要操作的卖单:")
        print("=" * 80)
        for a in alerts:
            print(f"  {a['code']} {a['name']}: 卖出 ¥{a['sell_amount']:,.2f} (约 {a['sell_shares']:,.2f} 份) @ NAV ¥{a['nav']:.4f}")
            print(f"    触发: {', '.join(f'+{t}%' for t in a['new_triggers'])}  当前浮盈 {a['pp']:+.2f}%")
    else:
        print()
        print("今日无需操作")

    db.close()


if __name__ == '__main__':
    main()
