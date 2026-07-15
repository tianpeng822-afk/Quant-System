import streamlit as st
import pandas as pd
import akshare as ak
from decimal import Decimal
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from loguru import logger
from app.scraper.nav_fetcher import _fetch_akshare_nav
from web.utils import get_db_session
from app.models import Holding

st.set_page_config(page_title="定投止盈回测", page_icon="📈", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)

st.title("📈 基金定投止盈回测")

st.markdown("""
> 评估“按月定投 + 达到目标收益率部分止盈”策略在指定基金上的历史表现。
""")

# ---- 参数配置 ----
with st.sidebar:
    st.header("⚙️ 回测参数设置")
    
    # 从数据库获取用户持仓基金
    db = get_db_session()
    holdings = db.query(Holding.fund_code, Holding.fund_name).distinct().all()
    fund_options = {h.fund_code: f"{h.fund_name} ({h.fund_code})" for h in holdings}
    
    if fund_options:
        fund_options["OTHER"] = "其它 (手动输入)"
        
        # 默认选中第一个，如果 163406 存在优先选 163406
        default_idx = 0
        if "163406" in fund_options:
            default_idx = list(fund_options.keys()).index("163406")
            
        selected_option = st.selectbox(
            "选择回测基金",
            options=list(fund_options.keys()),
            format_func=lambda x: fund_options[x],
            index=default_idx
        )
        if selected_option == "OTHER":
            fund_code = st.text_input("手动输入基金代码", value="163406")
        else:
            fund_code = selected_option
    else:
        fund_code = st.text_input("基金代码", value="163406", help="例如 163406（兴全合润混合）")
    
    st.subheader("🗓️ 时间设置")
    
    quick_time = st.radio(
        "快捷选择",
        ["自定义", "过去1年", "过去3年", "过去5年", "过去10年", "成立以来"],
        index=0,
        horizontal=True
    )
    
    today_date = datetime.today().date()
    from datetime import timedelta
    
    if quick_time == "过去1年":
        default_start = today_date - timedelta(days=365)
        default_end = today_date
    elif quick_time == "过去3年":
        default_start = today_date - timedelta(days=365*3)
        default_end = today_date
    elif quick_time == "过去5年":
        default_start = today_date - timedelta(days=365*5)
        default_end = today_date
    elif quick_time == "过去10年":
        default_start = today_date - timedelta(days=365*10)
        default_end = today_date
    elif quick_time == "成立以来":
        default_start = datetime(2000, 1, 1).date()
        default_end = today_date
    else:
        default_start = datetime(2010, 1, 1).date()
        default_end = today_date

    col_date1, col_date2 = st.columns(2)
    with col_date1:
        start_date_input = st.date_input("回测开始日期", value=default_start, key=f"start_date_{quick_time}")
    with col_date2:
        end_date_input = st.date_input("回测结束日期", value=default_end, key=f"end_date_{quick_time}")
    
    st.subheader("⏱️ 定投频率")
    invest_freq = st.selectbox("定投频率", ["每月", "每周"], index=0)
    
    if invest_freq == "每月":
        invest_day = st.number_input("每月定投日 (1-28)", min_value=1, max_value=28, value=1)
    else:
        invest_day = st.selectbox("每周定投日", options=[1,2,3,4,5], format_func=lambda x: ["周一","周二","周三","周四","周五"][x-1], index=0)
        
    monthly_amount = st.number_input("每次定投金额 (元)", value=1000.0, step=100.0)
    
    st.subheader("🎯 止盈策略设置")
    take_profit_strategy = st.radio("选择止盈策略", ["静态止盈 (固定目标)", "移动止盈 (Trailing Stop)", "不止盈"], index=0, horizontal=True)
    
    target_profit_pct = 99999.0
    trail_start_pct = 99999.0
    trail_tolerance_pct = 0.0
    sell_pct = 0.0
    
    if take_profit_strategy == "静态止盈 (固定目标)":
        target_profit_pct = st.number_input("静态止盈目标收益率 (%)", value=20.0, step=1.0, help="持仓收益率达到此数值时触发卖出")
        sell_pct = st.number_input("触发止盈卖出比例 (%)", value=50.0, step=10.0, help="达到止盈目标后，卖出当前持仓的百分比", key="static_sell_pct")
    elif take_profit_strategy == "移动止盈 (Trailing Stop)":
        trail_start_pct = st.number_input("移动止盈启动线 (%)", value=30.0, step=1.0, help="利润达到此百分比时，开启移动止盈监控")
        trail_tolerance_pct = st.number_input("回撤容忍度 (%)", value=8.0, step=1.0, help="从最高浮盈率回落此百分比时触发清仓")
        sell_pct = st.number_input("触发止盈卖出比例 (%)", value=100.0, step=10.0, help="移动止盈一般建议全仓或大比例卖出", key="trail_sell_pct")
    
    st.subheader("🌟 智能定投动态金额 (慧定投)")
    enable_smart_dca = st.checkbox("开启基于 250 日均线的智能定投", value=False, help="开启后，当基金净值跌破 250 日均线较多时，自动加倍买入；涨出均线较多时，自动减少买入。")
    if enable_smart_dca:
        st.caption("以下乘数将作用于您的【每次定投金额】")
        smart_low_multiplier = st.number_input("低估(极度冰点)区间乘数", value=2.0, step=0.1, help="净值低于年线 15% 以上时，买入金额的倍数")
        smart_normal_multiplier = st.number_input("正常区间乘数", value=1.0, step=0.1, help="净值在年线上下 15% 浮动时，买入金额的倍数")
        smart_high_multiplier = st.number_input("高估(过热)区间乘数", value=0.5, step=0.1, help="净值高于年线 15% 以上时，买入金额的倍数")
    else:
        smart_low_multiplier = 1.0
        smart_normal_multiplier = 1.0
        smart_high_multiplier = 1.0
        
    st.subheader("♻️ 抄底(回投)设置")
    enable_reinvest = st.checkbox("开启止盈资金回投", value=False, help="开启后，当【基金本身的净值】从历史最高点回撤达到设定比例时，将用之前的止盈资金自动抄底买入（自带 30 天冷静期）。")
    reinvest_threshold_pct = st.number_input("触发回投回撤阈值 (%)", value=15.0, step=1.0, help="当基金净值从前期高点下跌超过此百分比时触发，例如 15 代表回撤 15% 时抄底")
    reinvest_pct = st.number_input("抄底资金使用比例 (%)", value=100.0, step=10.0, help="每次抄底使用当前可用止盈资金的百分比")
    
    run_btn = st.button("🚀 开始回测", type="primary", use_container_width=True)

if run_btn:
    # 将当前所有参数全部存入 session_state，确保点击按鈕时的参数快照被完整保存下来
    st.session_state['backtest_params'] = {
        'fund_code': fund_code,
        'start_date_input': start_date_input,
        'end_date_input': end_date_input,
        'invest_freq': invest_freq,
        'invest_day': invest_day,
        'monthly_amount': monthly_amount,
        'take_profit_strategy': take_profit_strategy,
        'target_profit_pct': target_profit_pct,
        'trail_start_pct': trail_start_pct,
        'trail_tolerance_pct': trail_tolerance_pct,
        'sell_pct': sell_pct,
        'enable_smart_dca': enable_smart_dca,
        'smart_low_multiplier': smart_low_multiplier,
        'smart_normal_multiplier': smart_normal_multiplier,
        'smart_high_multiplier': smart_high_multiplier,
        'enable_reinvest': enable_reinvest,
        'reinvest_threshold_pct': reinvest_threshold_pct,
        'reinvest_pct': reinvest_pct,
    }

if 'backtest_params' in st.session_state:
    # 从 session_state 读取快照参数，而不是直接引用侧栏变量
    _p = st.session_state['backtest_params']
    fund_code = _p['fund_code']
    start_date_input = _p['start_date_input']
    end_date_input = _p['end_date_input']
    invest_freq = _p['invest_freq']
    invest_day = _p['invest_day']
    monthly_amount = _p['monthly_amount']
    take_profit_strategy = _p['take_profit_strategy']
    target_profit_pct = _p['target_profit_pct']
    trail_start_pct = _p['trail_start_pct']
    trail_tolerance_pct = _p['trail_tolerance_pct']
    sell_pct = _p['sell_pct']
    enable_smart_dca = _p['enable_smart_dca']
    smart_low_multiplier = _p['smart_low_multiplier']
    smart_normal_multiplier = _p['smart_normal_multiplier']
    smart_high_multiplier = _p['smart_high_multiplier']
    enable_reinvest = _p['enable_reinvest']
    reinvest_threshold_pct = _p['reinvest_threshold_pct']
    reinvest_pct = _p['reinvest_pct']
    
    if not fund_code:
        st.warning("请输入基金代码")
        st.stop()

    import os
    cache_file = f"data/{fund_code}_history_v2.csv"
    df = None
    
    with st.spinner(f"正在加载 {fund_code} 从成立至今的历史净值数据..."):
        if os.path.exists(cache_file):
            try:
                df = pd.read_csv(cache_file)
                st.toast(f"已加载本地缓存数据 ({len(df)} 条记录)。")
            except Exception as e:
                logger.error(f"读取本地缓存失败: {e}")
                
        if df is None or df.empty:
            try:
                st.toast("本地无缓存，正在从云端获取数据...")
                df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
                df_accum = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
                
                if df_unit is None or df_unit.empty or df_accum is None or df_accum.empty:
                    st.error("无法获取该基金数据，请检查代码是否正确（仅支持场外开放式基金）。")
                    st.stop()
                    
                # 兼容合并两份数据
                date_col_unit = "净值日期" if "净值日期" in df_unit.columns else df_unit.columns[0]
                date_col_accum = "净值日期" if "净值日期" in df_accum.columns else df_accum.columns[0]
                
                df_unit = df_unit.rename(columns={date_col_unit: "净值日期", "单位净值": "单位净值"})
                df_accum = df_accum.rename(columns={date_col_accum: "净值日期", "累计净值": "累计净值"})
                
                df = pd.merge(df_unit, df_accum[["净值日期", "累计净值"]], on="净值日期", how="left")
                df.attrs["name"] = df_unit.attrs.get("name", "")
                
                # 尝试保存到本地缓存
                if not os.path.exists("data"):
                    os.makedirs("data")
                df.to_csv(cache_file, index=False)
                st.toast(f"云端数据获取成功，已缓存到本地。")
            except Exception as e:
                st.error(f"数据获取失败: {e}")
                logger.exception(e)
                st.stop()
            
    # 数据预处理
    date_col = "净值日期"
    nav_col = "累计净值" if "累计净值" in df.columns else "单位净值"  # 优先使用累计净值，以消除分红拆分导致的净值断崖
    
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df[nav_col] = df[nav_col].astype(float)
    df = df.sort_values(by=date_col).reset_index(drop=True)
    
    # 计算 250 日均线和偏离度 (智能定投依据)，必须在时间过滤前计算
    df['MA250'] = df[nav_col].rolling(window=250, min_periods=1).mean()
    df['MA_deviation'] = (df[nav_col] - df['MA250']) / df['MA250']
    
    actual_start_date = df[date_col].min().date()
    
    # 过滤起止时间
    df = df[(df[date_col].dt.date >= start_date_input) & (df[date_col].dt.date <= end_date_input)].reset_index(drop=True)
    if df.empty:
        st.warning("所选时间段内没有数据，请调整起止时间。")
        st.stop()
        
    if actual_start_date > start_date_input:
        st.toast(f"💡 该基金成立于 {actual_start_date}，回测自成立日开始。")
        
    fund_name = str(df.attrs.get("name", fund_code))
    st.subheader(f"📊 回测结果: {fund_name} ({fund_code})")
    
    start_date = df[date_col].min().strftime("%Y-%m-%d")
    end_date = df[date_col].max().strftime("%Y-%m-%d")
    st.caption(f"回测区间: {start_date} 至 {end_date} (共 {len(df)} 个交易日)")

    # 计算基金自身的历史最大回撤（用于抄底触发）
    df['peak_nav'] = df[nav_col].cummax()
    df['fund_drawdown'] = (df[nav_col] - df['peak_nav']) / df['peak_nav']
    
    # ---- 核心回测逻辑 ----
    total_shares = 0.0      # 当前持有份额
    total_cost = 0.0        # 当前持仓总成本（用于计算当前收益率）
    
    total_invested = 0.0    # 累计投入真金白银
    cash_pool = 0.0  # 累计落袋为安的现金（即可用止盈资金）
    
    last_invest_period = None
    last_reinvest_date = None
    peak_profit_pct = 0.0   # 历史最高浮盈率（用于移动止盈）
    
    history_records = []
    trade_logs = []

    progress_bar = st.progress(0)
    total_rows = len(df)
    
    for idx, row in df.iterrows():
        current_date = row[date_col]
        current_nav = row[nav_col]
        fund_dd = row['fund_drawdown']
        
        if invest_freq == "每月":
            current_period = (current_date.year, current_date.month)
            should_invest = current_date.day >= invest_day
        else:
            current_period = (current_date.isocalendar()[0], current_date.isocalendar()[1])
            should_invest = (current_date.weekday() + 1) >= invest_day
        
        # 1. 定投买入逻辑
        if current_period != last_invest_period and should_invest:
            # 判断慧定投乘数
            current_multiplier = 1.0
            trade_type = "买入(定投)"
            if enable_smart_dca:
                ma_dev = row['MA_deviation']
                if pd.notna(ma_dev):
                    if ma_dev <= -0.15:
                        current_multiplier = smart_low_multiplier
                        trade_type = "买入(低估加倍)"
                    elif ma_dev >= 0.15:
                        current_multiplier = smart_high_multiplier
                        trade_type = "买入(高估缩减)"
                        
            actual_invest_amount = monthly_amount * current_multiplier
            
            # 执行定投买入
            buy_shares = actual_invest_amount / current_nav
            total_shares += buy_shares
            total_cost += actual_invest_amount
            total_invested += actual_invest_amount
            last_invest_period = current_period
            
            trade_logs.append({
                "日期": current_date.strftime("%Y-%m-%d"),
                "类型": trade_type,
                "净值": round(current_nav, 4),
                "发生金额": round(actual_invest_amount, 2),
                "发生份额": round(buy_shares, 2)
            })
            
        # 2. 每日检查止盈与抄底回投逻辑
        current_market_value = total_shares * current_nav
        
        profit_pct = 0.0
        if total_cost > 0:
            profit_pct = (current_market_value - total_cost) / total_cost
            
            trigger_sell = False
            sell_type_str = ""
            
            if take_profit_strategy == "静态止盈 (固定目标)":
                if profit_pct >= (target_profit_pct / 100.0):
                    trigger_sell = True
                    sell_type_str = "卖出(静态止盈)"
            elif take_profit_strategy == "移动止盈 (Trailing Stop)":
                if profit_pct > peak_profit_pct:
                    peak_profit_pct = profit_pct
                    
                if peak_profit_pct >= (trail_start_pct / 100.0):
                    if profit_pct <= peak_profit_pct - (trail_tolerance_pct / 100.0):
                        trigger_sell = True
                        sell_type_str = "卖出(移动止盈)"
            
            if trigger_sell:
                # 触发止盈
                sell_shares = total_shares * (sell_pct / 100.0)
                cash_out = sell_shares * current_nav
                
                # 更新账户
                cash_pool += cash_out
                total_shares -= sell_shares
                
                # 修复“连环止盈”Bug：重置剩余持仓成本
                total_cost = total_shares * current_nav  
                current_market_value = total_shares * current_nav
                peak_profit_pct = 0.0 # 重置历史最高利润
                
                trade_logs.append({
                    "日期": current_date.strftime("%Y-%m-%d"),
                    "类型": sell_type_str,
                    "净值": round(current_nav, 4),
                    "发生金额": round(cash_out, 2),
                    "发生份额": round(sell_shares, 2)
                })
            elif enable_reinvest and fund_dd <= -(reinvest_threshold_pct / 100.0):
                # 触发抄底回投 (30天冷静期)
                if last_reinvest_date is None or (current_date.date() - last_reinvest_date).days >= 30:
                    reinvest_amount = cash_pool * (reinvest_pct / 100.0)
                    if reinvest_amount >= 1.0:
                        buy_shares = reinvest_amount / current_nav
                        total_shares += buy_shares
                        total_cost += reinvest_amount
                        cash_pool -= reinvest_amount
                        current_market_value = total_shares * current_nav
                        last_reinvest_date = current_date.date()
                        
                        trade_logs.append({
                            "日期": current_date.strftime("%Y-%m-%d"),
                            "类型": "买入(抄底)",
                            "净值": round(current_nav, 4),
                            "发生金额": round(reinvest_amount, 2),
                            "发生份额": round(buy_shares, 2)
                        })
        
        # 记录每日快照用于画图
        history_records.append({
            "日期": current_date,
            "累计投入本金": total_invested,
            "累计变现金额": cash_pool,
            "当前持仓市值": current_market_value,
            "总权益(变现+市值)": cash_pool + current_market_value,
            "当前成本": total_cost,
            "基金净值": current_nav,
        })
        
        if idx % 500 == 0:
            progress_bar.progress(min(idx / total_rows, 1.0))
            
    progress_bar.empty()
    
    # ---- 结果统计与展示 ----
    history_df = pd.DataFrame(history_records)
    
    # 策略最大回撤
    history_df['equity_peak'] = history_df['总权益(变现+市值)'].cummax()
    history_df['strategy_drawdown'] = (history_df['总权益(变现+市值)'] - history_df['equity_peak']) / history_df['equity_peak'].replace(0, pd.NA) * 100
    strategy_max_dd = history_df['strategy_drawdown'].min() if not history_df.empty else 0.0
    
    # 基金本身最大回撤
    fund_max_dd = df['fund_drawdown'].min() * 100 if not df.empty else 0.0

    final_market_value = total_shares * df.iloc[-1][nav_col]
    absolute_profit = (cash_pool + final_market_value) - total_invested
    total_return_pct = (absolute_profit / total_invested * 100) if total_invested > 0 else 0.0
    
    # 计算平均年收益
    days = (df.iloc[-1][date_col] - df.iloc[0][date_col]).days
    years = days / 365.25
    
    import scipy.optimize
    
    # 提取现金流计算策略真实年化 (XIRR)
    cfs = []
    for log in trade_logs:
        if log["类型"].startswith("买入") and "抄底" not in log["类型"]:
            date_obj = datetime.strptime(log["日期"], "%Y-%m-%d").date()
            cfs.append((date_obj, -log["发生金额"]))
            
    final_date = df.iloc[-1][date_col].date()
    cfs.append((final_date, final_market_value + cash_pool))
    
    def xnpv(rate):
        if rate <= -0.9999:
            return float('inf')
        return sum([cf[1] / ((1 + rate) ** ((cf[0] - cfs[0][0]).days / 365.25)) for cf in cfs])
        
    try:
        if len(cfs) > 1:
            annual_return_pct = scipy.optimize.newton(xnpv, 0.1) * 100
        else:
            annual_return_pct = 0.0
    except:
        # XIRR 不收敛时的近似计算（假设资金平均占用期为一半）
        avg_years = years / 2
        annual_return_pct = (((final_market_value + cash_pool) / total_invested) ** (1 / avg_years) - 1) * 100 if total_invested > 0 and avg_years > 0 else 0.0
    
    # 三行三列布局
    col1, col2, col3 = st.columns(3)
    col1.metric("累计投入本金", f"¥ {total_invested:,.0f}")
    col2.metric("可用止盈资金", f"¥ {cash_pool:,.0f}")
    col3.metric("期末剩余市值", f"¥ {final_market_value:,.0f}")
    
    st.write("") # 增加行间距
    
    col4, col5, col6 = st.columns(3)
    col4.metric("绝对总收益", f"¥ {absolute_profit:,.0f}")
    
    # 计算基金本身的基准收益 (使用复合年化 CAGR)
    start_nav_val = df.iloc[0][nav_col]
    end_nav_val = df.iloc[-1][nav_col]
    fund_total_return = (end_nav_val - start_nav_val) / start_nav_val * 100 if start_nav_val > 0 else 0.0
    fund_annual_return = (((end_nav_val / start_nav_val) ** (1 / years) - 1) * 100) if start_nav_val > 0 and years > 0 else 0.0
    
    total_alpha = total_return_pct - fund_total_return
    annual_alpha = annual_return_pct - fund_annual_return
    
    col5.metric(
        "策略累计收益率", 
        f"{total_return_pct:.2f}%", 
        delta=f"{total_alpha:.2f}%", 
        help=f"基准：同期基金本身的累计收益率为 {fund_total_return:.2f}%。下方箭头及数字表示策略相较于一次性全仓买入产生的超额收益。"
    )
    col6.metric(
        "策略平均年化", 
        f"{annual_return_pct:.2f}%", 
        delta=f"{annual_alpha:.2f}%", 
        help=f"基准：同期基金本身的平均年化为 {fund_annual_return:.2f}%。下方箭头及数字表示策略相较于一次性全仓买入产生的超额年化收益。"
    )
    
    st.write("")
    
    col7, col8, col9 = st.columns(3)
    col7.metric("策略最大回撤", f"{strategy_max_dd:.2f}%")
    col8.metric("基金历史最大回撤", f"{fund_max_dd:.2f}%")
    
    dd_ratio = (strategy_max_dd / fund_max_dd) if fund_max_dd < 0 else 0.0
    dd_improvement = (1 - dd_ratio) * 100 if fund_max_dd < 0 else 0.0
    col9.metric("抗风险能力 (回撤改善)", f"+{dd_improvement:.1f}%", help="对比全仓买入该基金，此定投策略帮助您少承受了百分之几的回撤。正数代表策略能有效平滑风险。")
    
    st.divider()
    
    # 绘制曲线图
    history_df["盈利上限"] = history_df[["总权益(变现+市值)", "累计投入本金"]].max(axis=1)
    history_df["亏损下限"] = history_df[["总权益(变现+市值)", "累计投入本金"]].min(axis=1)
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # 0. 画基金净值（副坐标轴，半透明浅灰色）
    fig.add_trace(
        go.Scatter(x=history_df["日期"], y=history_df["基金净值"], mode='lines', name='基金累计净值 (副坐标)', line=dict(color='rgba(150, 150, 150, 0.5)', width=1.5)),
        secondary_y=True
    )
    
    # 1. 先画投入本金线作为基础
    fig.add_trace(go.Scatter(x=history_df["日期"], y=history_df["累计投入本金"], mode='lines', name='累计投入本金', line=dict(color='gray', dash='dash')), secondary_y=False)
    
    # 2. 画盈利区间（红色填充：从本金向上填到盈利上限）
    fig.add_trace(go.Scatter(
        x=history_df["日期"], y=history_df["盈利上限"], 
        mode='lines', line=dict(color='rgba(255,0,0,0)'), 
        fill='tonexty', fillcolor='rgba(255, 0, 0, 0.2)', name='浮盈区间', hoverinfo='skip'
    ))
    
    # 3. 把填充基准线重置回本金线
    fig.add_trace(go.Scatter(x=history_df["日期"], y=history_df["累计投入本金"], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='skip'))
    
    # 4. 画亏损区间（绿色填充：从本金向下填到亏损下限）
    fig.add_trace(go.Scatter(
        x=history_df["日期"], y=history_df["亏损下限"], 
        mode='lines', line=dict(color='rgba(0,255,0,0)'), 
        fill='tonexty', fillcolor='rgba(0, 255, 0, 0.3)', name='浮亏区间', hoverinfo='skip'
    ))
    
    # 5. 最后画出实际的总权益线
    fig.add_trace(go.Scatter(x=history_df["日期"], y=history_df["总权益(变现+市值)"], mode='lines', name='总权益 (持仓市值+已变现)', line=dict(color='red', width=2)))
    
    # 其他辅助线
    fig.add_trace(go.Scatter(x=history_df["日期"], y=history_df["当前持仓市值"], mode='lines', name='当前持仓市值', line=dict(color='blue', width=1)))
    fig.add_trace(go.Scatter(x=history_df["日期"], y=history_df["累计变现金额"], mode='lines', name='累计变现金额', line=dict(color='orange', width=1)))
    
    # 标记止盈点
    sells_df = pd.DataFrame([log for log in trade_logs if "卖出" in log["类型"]])
    if not sells_df.empty:
        sells_df["日期"] = pd.to_datetime(sells_df["日期"])
        # 合并当天总权益以便打点
        sells_plot_df = pd.merge(sells_df, history_df, on="日期", how="left")
        fig.add_trace(go.Scatter(
            x=sells_plot_df["日期"], 
            y=sells_plot_df["总权益(变现+市值)"], 
            mode='markers', 
            name='触发止盈', 
            marker=dict(color='orange', size=8, symbol='star')
        ))
        
    # 标记抄底点
    buys_dip_df = pd.DataFrame([log for log in trade_logs if "抄底" in log["类型"]])
    if not buys_dip_df.empty:
        buys_dip_df["日期"] = pd.to_datetime(buys_dip_df["日期"])
        buys_plot_df = pd.merge(buys_dip_df, history_df, on="日期", how="left")
        fig.add_trace(go.Scatter(
            x=buys_plot_df["日期"], 
            y=buys_plot_df["总权益(变现+市值)"], 
            mode='markers', 
            name='触发抄底', 
            marker=dict(color='magenta', size=12, symbol='triangle-up', line=dict(color='white', width=1.5))
        ))
        
    # 标记最大浮盈和最大浮亏
    history_df["绝对盈亏"] = history_df["总权益(变现+市值)"] - history_df["累计投入本金"]
    # 避免除以0
    history_df["盈亏比例"] = (history_df["绝对盈亏"] / history_df["累计投入本金"].replace(0, pd.NA)) * 100
    
    if not history_df.empty and not history_df["盈亏比例"].isna().all():
        max_profit_idx = history_df["盈亏比例"].idxmax()
        max_loss_idx = history_df["盈亏比例"].idxmin()
        max_abs_profit_idx = history_df["绝对盈亏"].idxmax()
        max_abs_loss_idx = history_df["绝对盈亏"].idxmin()
        
        max_profit_row = history_df.loc[max_profit_idx]
        max_loss_row = history_df.loc[max_loss_idx]
        max_abs_profit_row = history_df.loc[max_abs_profit_idx]
        max_abs_loss_row = history_df.loc[max_abs_loss_idx]
        
        # 1. 浮盈比例极值
        if pd.notna(max_profit_row["盈亏比例"]) and max_profit_row["盈亏比例"] > 0:
            abs_profit = max_profit_row["绝对盈亏"]
            fig.add_annotation(
                x=max_profit_row["日期"],
                y=max_profit_row["总权益(变现+市值)"],
                text=f"最大浮盈率: +{max_profit_row['盈亏比例']:.2f}% (¥{abs_profit:,.0f})",
                showarrow=True, arrowhead=1, arrowcolor="red", font=dict(color="red"), ay=-40
            )
            
        # 2. 浮亏比例极值
        if pd.notna(max_loss_row["盈亏比例"]) and max_loss_row["盈亏比例"] < 0:
            abs_loss = max_loss_row["绝对盈亏"]
            fig.add_annotation(
                x=max_loss_row["日期"],
                y=max_loss_row["总权益(变现+市值)"],
                text=f"最大浮亏率: {max_loss_row['盈亏比例']:.2f}% (¥{abs_loss:,.0f})",
                showarrow=True, arrowhead=1, arrowcolor="green", font=dict(color="green"), ay=40
            )

        # 3. 绝对盈利极值（如果日期和比例极值不同，则额外标注）
        if pd.notna(max_abs_profit_row["绝对盈亏"]) and max_abs_profit_row["绝对盈亏"] > 0:
            if max_abs_profit_idx != max_profit_idx:
                pct = max_abs_profit_row["盈亏比例"]
                fig.add_annotation(
                    x=max_abs_profit_row["日期"],
                    y=max_abs_profit_row["总权益(变现+市值)"],
                    text=f"最大绝对浮盈: ¥{max_abs_profit_row['绝对盈亏']:,.0f} (+{pct:.2f}%)",
                    showarrow=True, arrowhead=1, arrowcolor="darkred", font=dict(color="darkred"), ay=-70
                )

        # 4. 绝对亏损极值（如果日期和比例极值不同，则额外标注）
        if pd.notna(max_abs_loss_row["绝对盈亏"]) and max_abs_loss_row["绝对盈亏"] < 0:
            if max_abs_loss_idx != max_loss_idx:
                pct = max_abs_loss_row["盈亏比例"]
                fig.add_annotation(
                    x=max_abs_loss_row["日期"],
                    y=max_abs_loss_row["总权益(变现+市值)"],
                    text=f"最大绝对浮亏: ¥{max_abs_loss_row['绝对盈亏']:,.0f} ({pct:.2f}%)",
                    showarrow=True, arrowhead=1, arrowcolor="darkgreen", font=dict(color="darkgreen"), ay=70
                )
            
    fig.update_layout(
        title="资产走势对比",
        xaxis_title="日期",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    fig.update_yaxes(title_text="金额 (元)", secondary_y=False)
    fig.update_yaxes(title_text="基金累计净值", showgrid=False, secondary_y=True)
    
    st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    st.subheader("📝 交易流水 (定投 & 止盈)")
    trades_df = pd.DataFrame(trade_logs)
    if not trades_df.empty:
        st.dataframe(trades_df.style.format({
            "净值": "{:.4f}",
            "发生金额": "{:,.2f}",
            "发生份额": "{:,.2f}"
        }), use_container_width=True, height=300)
    else:
        st.info("暂无交易流水")
