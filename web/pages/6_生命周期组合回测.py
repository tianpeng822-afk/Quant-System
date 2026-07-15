# Cache buster 1
import streamlit as st
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import scipy.optimize
import os
import time

st.set_page_config(page_title="生命周期组合回测", page_icon="🧮", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)

st.title("🧮 生命周期组合定投回测 (TDF)")

st.markdown("""
> 模拟真实的**生命周期资产配置 (Glide Path)**。前期本金少，采用高风险进取型配置；当投入本金达到阈值后，人性厌恶波动，系统将自动触发防守，重组存量资产并调整后续定投比例。
""")

# ---- 参数配置 ----
with st.sidebar:
    st.header("⚙️ 组合与参数设置")
    
    st.subheader("1. 基金组合选择")
    fund_A = st.text_input("基金 A (例如：主动型)", value="003376", help="例如 003376 广发核心竞争力")
    fund_B = st.text_input("基金 B (例如：宽基沪深300)", value="000051", help="例如 000051 华夏沪深300")
    fund_C = st.text_input("基金 C (可选：海外标普500)", value="", help="若只回测2只基金，请清空此处")
    
    st.subheader("2. 时间与定投设置")
    quick_time = st.radio(
        "快捷选择",
        ["自定义", "过去1年", "过去3年", "过去5年", "过去10年", "成立以来"],
        index=4,
        horizontal=True
    )
    
    today_date = datetime.today().date()
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
        start_date_input = st.date_input("开始日期", value=default_start)
    with col_date2:
        end_date_input = st.date_input("结束日期", value=default_end)
        
    monthly_amount = st.number_input("每月定投金额 (元)", value=1000.0, step=100.0)
    
    st.subheader("3. 阶梯防守与重平衡设置")
    enable_annual_rebalance = st.checkbox("每年 1 月 1 日自动重平衡到当前目标比例", value=True)
    enable_threshold_rebalance = st.checkbox("启用阈值动态重平衡", value=False, help="当资产占比偏离目标比例过大时自动触发重平衡（强制高抛低吸）")
    drift_threshold = 10.0
    if enable_threshold_rebalance:
        drift_threshold = st.number_input("触发偏离阈值 (%)", value=10.0, step=1.0, help="例如目标占比30%，若实际占比涨至40%或跌至20%（偏离10%），则自动重平衡。")
    
    st.caption("【阶段一】起步期 (< 市值阈值1)")
    col1, col2, col3 = st.columns(3)
    p1_a = col1.number_input("A%", value=70, min_value=0, max_value=100, key="p1a")
    p1_b = col2.number_input("B%", value=30, min_value=0, max_value=100, key="p1b")
    p1_c = col3.number_input("C%", value=0, min_value=0, max_value=100, key="p1c")
    if p1_a + p1_b + p1_c != 100:
        st.error("阶段一比例总和必须为 100%")
        
    st.caption("【阶段二】跨越阈值 1")
    thresh_2 = st.number_input("触发市值阈值 1 (元)", value=150000.0, step=10000.0)
    col4, col5, col6 = st.columns(3)
    p2_a = col4.number_input("A%", value=80, min_value=0, max_value=100, key="p2a")
    p2_b = col5.number_input("B%", value=20, min_value=0, max_value=100, key="p2b")
    p2_c = col6.number_input("C%", value=0, min_value=0, max_value=100, key="p2c")
    if p2_a + p2_b + p2_c != 100:
        st.error("阶段二比例总和必须为 100%")
        
    st.caption("【阶段三】跨越阈值 2")
    thresh_3 = st.number_input("触发市值阈值 2 (元)", value=300000.0, step=10000.0)
    col7, col8, col9 = st.columns(3)
    p3_a = col7.number_input("A%", value=90, min_value=0, max_value=100, key="p3a")
    p3_b = col8.number_input("B%", value=10, min_value=0, max_value=100, key="p3b")
    p3_c = col9.number_input("C%", value=0, min_value=0, max_value=100, key="p3c")
    if p3_a + p3_b + p3_c != 100:
        st.error("阶段三比例总和必须为 100%")
        
    run_btn = st.button("🚀 开始生命周期组合回测", type="primary", use_container_width=True)

@st.cache_data(ttl=3600)
def load_fund_data(fund_code):
    cache_file = f"data/{fund_code}_history_v2.csv"
    df = None
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file)
        if '累计净值' not in df.columns:
            df = None
            
    if df is None or df.empty:
        from tenacity import retry, stop_after_attempt, wait_fixed
        
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
        def fetch_unit(c): return ak.fund_open_fund_info_em(symbol=c, indicator="单位净值走势")
        
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
        def fetch_accum(c): return ak.fund_open_fund_info_em(symbol=c, indicator="累计净值走势")

        try:
            df_unit = fetch_unit(fund_code)
            df_accum = None
            try:
                df_accum = fetch_accum(fund_code)
            except:
                pass
                
            if df_unit is not None and not df_unit.empty:
                if df_accum is not None and not df_accum.empty:
                    df = pd.merge(df_unit, df_accum, on="净值日期", how="inner")
                else:
                    df = df_unit.copy()
                    df['累计净值'] = df['单位净值']
                    
                if not os.path.exists('data'):
                    os.makedirs('data')
                df.to_csv(cache_file, index=False)
        except Exception as e:
            return None
            
    if df is not None and not df.empty and '累计净值' in df.columns:
        df['净值日期'] = pd.to_datetime(df['净值日期'])
        df = df.sort_values(by='净值日期').reset_index(drop=True)
        return df[['净值日期', '累计净值']].rename(columns={'累计净值': f'NAV_{fund_code}'})
    return None

if run_btn:
    fund_A = fund_A.strip()
    fund_B = fund_B.strip()
    fund_C = fund_C.strip()
    
    if not (fund_A and fund_B):
        st.warning("请至少输入 A 和 B 两只基金代码")
        st.stop()
        
    if (p1_a + p1_b + p1_c != 100) or (p2_a + p2_b + p2_c != 100):
        st.warning("资金分配比例相加必须等于100")
        st.stop()

    with st.spinner("正在拉取并对齐多只基金的净值数据..."):
        df_A = load_fund_data(fund_A)
        df_B = load_fund_data(fund_B)
        df_C = load_fund_data(fund_C) if fund_C else None
        
        if df_A is None or df_B is None:
            st.error("A或B基金数据拉取失败，请检查代码是否正确。")
            st.stop()
        if fund_C and df_C is None:
            st.error("C基金数据拉取失败。")
            st.stop()
            
        df_merged = pd.merge(df_A, df_B, on='净值日期', how='outer')
        if fund_C:
            df_merged = pd.merge(df_merged, df_C, on='净值日期', how='outer')
        df_merged = df_merged.sort_values('净值日期').reset_index(drop=True)
        # 前向填充处理非交易日的净值差异
        df_merged = df_merged.ffill()
        df_merged = df_merged.dropna().reset_index(drop=True)
        
        # 过滤起止时间
        start_dt = pd.to_datetime(start_date_input)
        end_dt = pd.to_datetime(end_date_input)
        df_merged = df_merged[(df_merged['净值日期'] >= start_dt) & (df_merged['净值日期'] <= end_dt)].reset_index(drop=True)
        
        if df_merged.empty:
            st.error("所选时间段内，所选基金没有重叠的交易记录，请缩短回测区间。")
            st.stop()

    st.subheader("📊 回测结果: 生命周期资产配置")
    st.caption(f"回测区间: {df_merged['净值日期'].iloc[0].date()} 至 {df_merged['净值日期'].iloc[-1].date()} (共 {len(df_merged)} 天)")

    # ---- 核心回测逻辑 ----
    shares_A, shares_B, shares_C = 0.0, 0.0, 0.0
    total_invested = 0.0
    portfolio_shares = 0.0
    
    last_invest_period = None
    in_defense_mode = False
    
    trade_logs = []
    history_records = []
    
    progress_bar = st.progress(0)
    total_rows = len(df_merged)
    
    r1_A, r1_B, r1_C = p1_a / 100.0, p1_b / 100.0, p1_c / 100.0
    r2_A, r2_B, r2_C = p2_a / 100.0, p2_b / 100.0, p2_c / 100.0
    r3_A, r3_B, r3_C = p3_a / 100.0, p3_b / 100.0, p3_c / 100.0

    target_rA, target_rB, target_rC = r1_A, r1_B, r1_C
    current_phase = 1
    last_rebalance_year = None
    
    for idx, row in df_merged.iterrows():
        current_date = row['净值日期']
        nav_A = float(row[f'NAV_{fund_A}'])
        nav_B = float(row[f'NAV_{fund_B}'])
        nav_C = float(row[f'NAV_{fund_C}']) if fund_C else 1.0
        
        current_period = (current_date.year, current_date.month)
        
        # 每日计算当前总市值
        total_market_value = shares_A * nav_A + shares_B * nav_B + shares_C * nav_C
        current_portfolio_nav = total_market_value / portfolio_shares if portfolio_shares > 0 else 1.0
        
        trigger_rebalance = False
        reason = ""
        
        # 仅在每年1月1日（当年第一个交易日）进行市值评估和重平衡
        if enable_annual_rebalance and current_date.month == 1 and current_date.year != last_rebalance_year:
            if current_date.year != df_merged['净值日期'].iloc[0].year or total_invested > 0:
                # 只在这一天按照【持仓总市值】计算所处阶段
                new_phase = current_phase
                if total_market_value >= thresh_3:
                    new_phase = 3
                    target_rA, target_rB, target_rC = r3_A, r3_B, r3_C
                elif total_market_value >= thresh_2:
                    new_phase = 2
                    target_rA, target_rB, target_rC = r2_A, r2_B, r2_C
                else:
                    new_phase = 1
                    target_rA, target_rB, target_rC = r1_A, r1_B, r1_C
                    
                if new_phase != current_phase:
                    reason = f"🚀 年度重平衡 + 切换至阶段 {new_phase} (当日市值 {total_market_value:,.0f})"
                else:
                    reason = "⚖️ 年度定期自动重平衡"
                    
                trigger_rebalance = True
                current_phase = new_phase
                
            last_rebalance_year = current_date.year
            
        # --- 新增: 阈值动态重平衡 ---
        if not trigger_rebalance and enable_threshold_rebalance and total_market_value > 0:
            actual_rA = (shares_A * nav_A) / total_market_value
            actual_rB = (shares_B * nav_B) / total_market_value
            actual_rC = (shares_C * nav_C) / total_market_value if fund_C else 0.0
            
            # 检查是否偏离超过阈值
            if abs(actual_rA - target_rA) >= drift_threshold / 100.0 or \
               abs(actual_rB - target_rB) >= drift_threshold / 100.0 or \
               (fund_C and abs(actual_rC - target_rC) >= drift_threshold / 100.0):
                trigger_rebalance = True
                reason = f"⚖️ 偏离阈值动态重平衡 (A实际占比 {actual_rA*100:.1f}%)"

        if trigger_rebalance and total_invested > 0:
            shares_A = (total_market_value * target_rA) / nav_A if nav_A else 0
            shares_B = (total_market_value * target_rB) / nav_B if nav_B else 0
            shares_C = (total_market_value * target_rC) / nav_C if fund_C and nav_C else 0
            
            trade_logs.append({
                "日期": current_date.strftime("%Y-%m-%d"),
                "类型": reason,
                "总本金": total_invested,
                "重组市值": round(total_market_value, 2)
            })

        # 每月定投
        if current_period != last_invest_period and current_date.day >= 1:
            t_type = f"买入(阶段{current_phase})"
                
            invest_A = monthly_amount * target_rA
            invest_B = monthly_amount * target_rB
            invest_C = monthly_amount * target_rC
            
            shares_A += invest_A / nav_A if nav_A else 0
            shares_B += invest_B / nav_B if nav_B else 0
            shares_C += invest_C / nav_C if fund_C and nav_C else 0
            
            total_invested += monthly_amount
            last_invest_period = current_period
            portfolio_shares += monthly_amount / current_portfolio_nav
            
            trade_logs.append({
                "日期": current_date.strftime("%Y-%m-%d"),
                "类型": t_type,
                "总本金": total_invested,
                "发生金额": monthly_amount
            })

        # 每日记录
        mv_A = shares_A * nav_A
        mv_B = shares_B * nav_B
        mv_C = shares_C * nav_C if fund_C else 0.0
        total_mv = mv_A + mv_B + mv_C
        daily_portfolio_nav = total_mv / portfolio_shares if portfolio_shares > 0 else 1.0
        
        history_records.append({
            "日期": current_date,
            "累计投入本金": total_invested,
            "A持仓市值": mv_A,
            "B持仓市值": mv_B,
            "C持仓市值": mv_C,
            "组合总市值": total_mv,
            "组合单位净值": daily_portfolio_nav
        })
        
        if idx % 500 == 0:
            progress_bar.progress(min(idx / total_rows, 1.0))
            
    progress_bar.empty()
    
    # 统计展示
    history_df = pd.DataFrame(history_records)
    final_row = history_df.iloc[-1]
    final_market_value = final_row["组合总市值"]
    absolute_profit = final_market_value - total_invested
    total_return_pct = (absolute_profit / total_invested * 100) if total_invested > 0 else 0.0
    
    # 计算最大回撤 (剥离定投本金干扰，采用单位净值法)
    history_df['最高净值'] = history_df['组合单位净值'].cummax()
    history_df['回撤'] = (history_df['组合单位净值'] - history_df['最高净值']) / history_df['最高净值']
    
    trough_idx = history_df['回撤'].idxmin()
    max_drawdown = history_df.loc[trough_idx, '回撤'] * 100
    
    # 找到最大回撤区间
    trough_date = history_df.loc[trough_idx, '日期']
    peak_value = history_df.loc[trough_idx, '最高净值']
    peak_idx = history_df.loc[:trough_idx][history_df.loc[:trough_idx, '组合单位净值'] == peak_value].index[0]
    peak_date = history_df.loc[peak_idx, '日期']
    
    # 找到修复日期
    recovery_slice = history_df.loc[trough_idx:][history_df.loc[trough_idx:, '组合单位净值'] >= peak_value]
    recovery_date = recovery_slice.iloc[0]['日期'] if not recovery_slice.empty else None
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("累计投入本金", f"¥ {total_invested:,.0f}")
    col2.metric("期末总市值", f"¥ {final_market_value:,.0f}")
    col3.metric("绝对总收益", f"¥ {absolute_profit:,.0f}", f"{total_return_pct:.2f}% 累计")
    col5.metric("最大回撤", f"{max_drawdown:.2f}%")
    
    # XIRR
    cfs = []
    for log in trade_logs:
        if "买入" in log["类型"]:
            d_obj = datetime.strptime(log["日期"], "%Y-%m-%d").date()
            cfs.append((d_obj, -log.get("发生金额", 0)))
    cfs.append((history_df.iloc[-1]["日期"].date(), final_market_value))
    
    def xnpv(rate):
        if rate <= -0.9999: return float('inf')
        return sum([cf[1] / ((1 + rate) ** ((cf[0] - cfs[0][0]).days / 365.25)) for cf in cfs])
        
    try:
        annual_return_pct = scipy.optimize.newton(xnpv, 0.1) * 100
        col4.metric("年化(XIRR)", f"{annual_return_pct:.2f}%")
    except Exception:
        col4.metric("年化(XIRR)", "计算失败")
    
    st.markdown("---")
    
    # 画图
    # 画图
    st.subheader("📈 组合资产规模与配比演变")
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.05, 
        row_heights=[0.7, 0.3]
    )
    
    fig.add_trace(
        go.Scatter(x=history_df['日期'], y=history_df['累计投入本金'], name="累计投入本金 (成本)", line=dict(color='black', width=2, dash='dash')),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=history_df['日期'], y=history_df['组合总市值'], name="组合总市值", line=dict(color='red', width=3)),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=history_df['日期'], y=history_df['A持仓市值'], name=f"{fund_A}(A) 市值", stackgroup='one', line=dict(width=0)),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=history_df['日期'], y=history_df['B持仓市值'], name=f"{fund_B}(B) 市值", stackgroup='one', line=dict(width=0)),
        row=1, col=1
    )
    if fund_C:
        fig.add_trace(
            go.Scatter(x=history_df['日期'], y=history_df['C持仓市值'], name=f"{fund_C}(C) 市值", stackgroup='one', line=dict(width=0)),
            row=1, col=1
        )

    # 标记调仓点
    rebal_dates_thresh, rebal_mvs_thresh, rebal_texts_thresh = [], [], []
    rebal_dates_annual, rebal_mvs_annual, rebal_texts_annual = [], [], []
    
    for log in trade_logs:
        if "重平衡" in log.get("类型", ""):
            if "阈值" in log["类型"]:
                rebal_dates_thresh.append(log["日期"])
                rebal_mvs_thresh.append(log.get("重组市值", 0))
                rebal_texts_thresh.append(log["类型"])
            else:
                rebal_dates_annual.append(log["日期"])
                rebal_mvs_annual.append(log.get("重组市值", 0))
                rebal_texts_annual.append(log["类型"])
                
    if rebal_dates_thresh:
        fig.add_trace(
            go.Scatter(
                x=rebal_dates_thresh, y=rebal_mvs_thresh, mode="markers", name="动态阈值触发点",
                marker=dict(symbol="star", size=14, color="gold", line=dict(width=1, color="black")),
                text=rebal_texts_thresh,
                hovertemplate="%{x}<br>市值: %{y:,.0f}<br>%{text}<extra></extra>"
            ),
            row=1, col=1
        )
        
    if rebal_dates_annual:
        fig.add_trace(
            go.Scatter(
                x=rebal_dates_annual, y=rebal_mvs_annual, mode="markers", name="年度重平衡/阶段切换",
                marker=dict(symbol="triangle-down", size=10, color="cyan", line=dict(width=1, color="black")),
                text=rebal_texts_annual,
                hovertemplate="%{x}<br>市值: %{y:,.0f}<br>%{text}<extra></extra>"
            ),
            row=1, col=1
        )

    # 添加绝对盈亏子图 (A股习惯：红涨绿跌)
    history_df['绝对盈亏'] = history_df['组合总市值'] - history_df['累计投入本金']
    profit_colors = ['rgba(255, 50, 50, 0.8)' if val >= 0 else 'rgba(50, 255, 50, 0.8)' for val in history_df['绝对盈亏']]
    fig.add_trace(
        go.Bar(x=history_df['日期'], y=history_df['绝对盈亏'], name="绝对盈亏", marker_color=profit_colors),
        row=2, col=1
    )

    fig.update_layout(
        height=800,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    # 在图中标记最大回撤和修复区间
    if peak_date != trough_date:
        fig.add_vrect(
            x0=peak_date, x1=trough_date,
            fillcolor="rgba(255, 0, 0, 0.2)",
            layer="below", line_width=0,
            annotation_text=f"最大回撤 {max_drawdown:.1f}%", annotation_position="top left",
            annotation_font_color="red"
        )
    if recovery_date and recovery_date != trough_date:
        days_to_recover = (pd.to_datetime(recovery_date) - pd.to_datetime(peak_date)).days
        fig.add_vrect(
            x0=trough_date, x1=recovery_date,
            fillcolor="rgba(0, 255, 0, 0.2)",
            layer="below", line_width=0,
            annotation_text=f"修复耗时 {days_to_recover}天", annotation_position="top left",
            annotation_font_color="green"
        )
    elif not recovery_date and peak_date != trough_date:
        fig.add_vrect(
            x0=trough_date, x1=history_df['日期'].iloc[-1],
            fillcolor="rgba(255, 165, 0, 0.2)",
            layer="below", line_width=0,
            annotation_text=f"尚未修复", annotation_position="top left",
            annotation_font_color="orange"
        )

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("查看组合交易与调仓流水记录"):
        st.dataframe(pd.DataFrame(trade_logs), use_container_width=True)
