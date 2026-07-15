"""
📊 持仓分析页面 — 深度分析每只基金的持仓状态、净值历史与风控情况
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from decimal import Decimal

import akshare as ak
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from web.utils import get_db_session, fmt_money, fmt_pct
from app.models import Holding, NavHistory, Account, Transaction

st.set_page_config(page_title="持仓分析 · 我的基金", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)


st.markdown("# 持仓分析")
st.caption("查看每只基金的详细持仓状态、净值历史走势与风控预警")
st.markdown("---")

# ── 加载数据 ──────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_holdings():
    db = get_db_session()
    try:
        return db.query(Holding).filter(Holding.shares > 0).all()
    finally:
        db.close()

holdings_all = load_holdings()

with st.sidebar:
    st.markdown("### 账户视图切换")
    from app.models import Account
    accounts_list = get_db_session().query(Account).filter(Account.is_active == True).all()
    account_options = {"all": "全账户汇总"}
    for acc in accounts_list:
        account_options[acc.id] = f"{acc.name}"
    
    if 'selected_account_id' not in st.session_state:
        st.session_state.selected_account_id = "all"
        
    def on_account_change():
        st.session_state.selected_account_id = st.session_state._account_selector

    current_val = st.session_state.selected_account_id
    
    st.selectbox(
        "选择要查看的账户:",
        options=list(account_options.keys()),
        format_func=lambda x: account_options[x],
        index=list(account_options.keys()).index(current_val) if current_val in account_options else 0,
        key="_account_selector",
        on_change=on_account_change
    )
    st.markdown("---")

if st.session_state.selected_account_id == "all":
    holdings = holdings_all
else:
    holdings = [h for h in holdings_all if h.account_id == st.session_state.selected_account_id]

if not holdings:
    st.info("暂无持仓数据，请先在「流水录入」页面添加申购记录")
    st.stop()

# ── 获取全局估值数据 ───────────────────────────────────────────
@st.cache_data(ttl=3600*12)
def load_all_valuations(indices):
    results = {}
    try:
        import akshare as ak
    except ImportError:
        return results
        
    for symbol in indices:
        if not symbol: continue
        try:
            df_pe = ak.stock_index_pe_lg(symbol=symbol)
            if df_pe is not None and not df_pe.empty:
                pe_col = '滚动市盈率' if '滚动市盈率' in df_pe.columns else df_pe.columns[-1]
                current_pe = float(df_pe[pe_col].iloc[-1])
                pe_series = df_pe[pe_col].dropna()
                pe_pct = (pe_series < current_pe).sum() / len(pe_series) * 100
                results[symbol] = pe_pct
        except Exception:
            pass
    return results

unique_indices = set([h.benchmark_index for h in holdings if h.benchmark_index])
valuation_dict = load_all_valuations(unique_indices)

# ── 风控总览卡片 ───────────────────────────────────────────────
st.markdown("### 风控状态总览")

for i, h in enumerate(holdings):
    if i % 3 == 0:
        risk_cols = st.columns(3)

    pnl_pct = float(h.unrealized_pnl_pct or 0)
    dd      = float(h.current_drawdown  or 0)
    val_pct = valuation_dict.get(h.benchmark_index)
    
    with risk_cols[i % 3]:
        # 判断是否触发移动止盈
        trailing_triggered = False
        if h.trailing_stop_start_pct and h.peak_pnl_pct and float(h.peak_pnl_pct) >= float(h.trailing_stop_start_pct):
            if h.trailing_stop_tolerance_pct:
                if pnl_pct <= float(h.peak_pnl_pct) - float(h.trailing_stop_tolerance_pct):
                    trailing_triggered = True

        status_label = "正常持仓"
        
        # 组合预警矩阵判断
        if trailing_triggered and val_pct is not None and val_pct > 80:
            status_label = "极度危险(强卖)"
        elif trailing_triggered and val_pct is not None and val_pct < 20:
            status_label = "震荡止盈(观望)"
        elif not trailing_triggered and val_pct is not None and val_pct < 20:
            status_label = "击球区(加仓)"
        elif not trailing_triggered and val_pct is not None and val_pct > 80:
            status_label = "泡沫区(停买)"
        elif trailing_triggered:
            status_label = "移动止盈触发"
        else:
            # 退回到静态防线
            if h.target_stop_profit and pnl_pct >= float(h.target_stop_profit):
                status_label = "静态止盈"
            elif h.target_stop_loss and dd <= float(h.target_stop_loss):
                status_label = "静态止损"

        with st.container(border=True):
            st.caption(f"{h.fund_code}")
            st.markdown(f"**{h.fund_name[:8]}**")
            st.metric(label=status_label, value=f"{pnl_pct:+.2f}%")

st.markdown("---")

# ── 持仓明细表格 ───────────────────────────────────────────────
st.markdown("### 持仓明细汇总")

rows = []
for h in sorted(holdings, key=lambda x: float(x.market_value or 0), reverse=True):
    rows.append({
        "基金代码":   h.fund_code,
        "基金名称":   h.fund_name,
        "资产类别":   h.fund_category or "未分类",
        "持有份额":   float(h.shares),
        "最新净值":   float(h.latest_nav or 0),
        "市值(元)":  float(h.market_value or 0),
        "摊薄均价":   float(h.avg_cost_price or 0),
        "总成本(元)": float(h.total_cost or 0),
        "浮动盈亏(元)": float(h.unrealized_pnl or 0),
        "盈亏率(%)":  float(h.unrealized_pnl_pct or 0),
        "历史最高净值": float(h.peak_nav or 0),
        "当前回撤(%)": float(h.current_drawdown or 0),
        "最高浮盈(%)": float(h.peak_pnl_pct or 0),
        "止盈目标(%)": float(h.target_stop_profit) if h.target_stop_profit else None,
        "止损阈值(%)": float(h.target_stop_loss) if h.target_stop_loss else None,
    })

df = pd.DataFrame(rows)
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "市值(元)":   st.column_config.NumberColumn(format="¥%.2f"),
        "总成本(元)": st.column_config.NumberColumn(format="¥%.2f"),
        "浮动盈亏(元)": st.column_config.NumberColumn(format="¥%.2f"),
        "盈亏率(%)":  st.column_config.NumberColumn(format="%.2f%%"),
        "当前回撤(%)": st.column_config.NumberColumn(format="%.2f%%"),
        "最高浮盈(%)": st.column_config.NumberColumn(format="%.2f%%"),
        "持有份额":   st.column_config.NumberColumn(format="%.4f"),
    }
)

st.markdown("---")

# ── 整体持仓 AI 深度诊断 ───────────────────────────────────────
st.markdown("### :material/smart_toy: 整体持仓 AI 深度诊断")
st.caption("基于您当前的整体仓位结构、盈亏情况，生成全局调仓优化建议。")

if st.button("呼叫 DeepSeek 分析我的持仓结构", type="primary"):
    if not holdings:
        st.warning("暂无持仓数据可供分析。")
    else:
        with st.spinner("正在唤醒 DeepSeek 分析诊断，请耐心等待（约需 10-20 秒）..."):
            from app.ai.deepseek import call_deepseek_portfolio_analysis
            
            total_mv = sum(float(h.market_value or 0) for h in holdings)
            total_cost = sum(float(h.total_cost or 0) for h in holdings)
            total_unrealized = sum(float(h.unrealized_pnl or 0) for h in holdings)
            total_pnl_pct = (total_unrealized / total_cost * 100) if total_cost > 0 else 0.0
            
            holdings_summary = []
            for h in sorted(holdings, key=lambda x: float(x.market_value or 0), reverse=True):
                mv = float(h.market_value or 0)
                weight = (mv / total_mv * 100) if total_mv > 0 else 0.0
                holdings_summary.append({
                    "fund_name": h.fund_name,
                    "fund_code": h.fund_code,
                    "total_cost": float(h.total_cost or 0),
                    "market_value": mv,
                    "weight": weight,
                    "unrealized_pnl_pct": float(h.unrealized_pnl_pct or 0)
                })
            
            report = call_deepseek_portfolio_analysis(
                holdings_summary=holdings_summary,
                total_mv=total_mv,
                total_cost=total_cost,
                total_pnl_pct=total_pnl_pct
            )
            
        st.success("诊断完成！")
        with st.container(border=True):
            st.markdown(report)

st.markdown("---")

# ── 单只基金深度分析 ───────────────────────────────────────────
st.markdown("### 单只基金深度分析")

fund_options = {f"{h.fund_name}（{h.fund_code}）": h for h in holdings}
selected_label = st.selectbox("选择基金", options=list(fund_options.keys()))
selected = fund_options[selected_label]

# 从 nav_history 读取历史净值
@st.cache_data(ttl=300)
def load_nav_history(fund_code: str):
    db = get_db_session()
    try:
        records = (
            db.query(NavHistory)
            .filter_by(fund_code=fund_code)
            .order_by(NavHistory.nav_date.asc())
            .all()
        )
        return records
    finally:
        db.close()

# 从流水表读取历史买入点
@st.cache_data(ttl=300)
def load_buy_points(fund_code: str):
    db = get_db_session()
    try:
        from app.models.transaction import TransactionType as TxType
        txs = (
            db.query(Transaction)
            .filter(Transaction.fund_code == fund_code,
                    Transaction.tx_type == TxType.BUY)
            .order_by(Transaction.trade_date.asc())
            .all()
        )
        return txs
    finally:
        db.close()

nav_records = load_nav_history(selected.fund_code)
buy_points  = load_buy_points(selected.fund_code)

tab1, tab2, tab3 = st.tabs(["净值走势", "风控设置", "估值温度计"])

with tab1:
    if nav_records:
        df_nav = pd.DataFrame([
            {"日期": r.nav_date, "单位净值": float(r.unit_nav),
             "累计净值": float(r.accum_nav or r.unit_nav)}
            for r in nav_records
        ])

        fig = go.Figure()

        # 净值曲线
        fig.add_trace(go.Scatter(
            x=df_nav["日期"], y=df_nav["单位净值"],
            name="单位净值", mode="lines",
            line=dict(color="#FF4B4B", width=2),
            fill="tozeroy", fillcolor="rgba(255,75,75,0.05)",
        ))

        # 买入成本线
        avg_cost = float(selected.avg_cost_price or 0)
        if avg_cost > 0 and not df_nav.empty:
            fig.add_hline(
                y=avg_cost, line_dash="dash",
                line_color="#F59E0B", line_width=1.5,
                annotation_text=f"  摊薄均价 {avg_cost:.4f}",
                annotation_font_color="#F59E0B",
            )

        # 历史最高净值线（回撤基准）
        peak_nav = float(selected.peak_nav or 0)
        if peak_nav > 0 and not df_nav.empty:
            fig.add_hline(
                y=peak_nav, line_dash="dot",
                line_color="#6699cc", line_width=1,
                annotation_text=f"  历史最高 {peak_nav:.4f}",
                annotation_font_color="#6699cc",
            )

        # 买入标记点
        if buy_points:
            buy_df = pd.DataFrame([
                {"日期": t.trade_date, "净值": float(t.nav_price),
                 "份额": float(t.shares), "金额": float(t.amount)}
                for t in buy_points
            ])
            fig.add_trace(go.Scatter(
                x=buy_df["日期"], y=buy_df["净值"],
                name="买入点", mode="markers",
                marker=dict(color="#3B82F6", size=9, symbol="triangle-up"),
                hovertemplate="买入<br>净值：%{y:.4f}<br>份额：%{customdata[0]:.4f}<extra></extra>",
                customdata=buy_df[["份额"]].values,
            ))

        fig.update_layout(
            legend=dict(orientation="h", y=1.08, x=0),
            margin=dict(l=0, r=0, t=30, b=0),
            height=380,
            xaxis=dict(showgrid=True),
            yaxis=dict(showgrid=True, tickprefix="¥"),
            hovermode="x unified",
            title=dict(
                text=f"{selected.fund_name}（{selected.fund_code}）净值走势",
                font=dict(size=14), x=0,
            )
        )
        st.plotly_chart(fig, use_container_width=True)

        # 基本指标面板
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("持有份额", f"{float(selected.shares):,.4f}")
        m2.metric("当前市值", f"¥{float(selected.market_value or 0):,.2f}")
        m3.metric("浮动盈亏",
                  fmt_money(selected.unrealized_pnl),
                  delta=fmt_pct(selected.unrealized_pnl_pct))
        m4.metric("当前回撤", fmt_pct(selected.current_drawdown))
    else:
        st.warning("该基金暂无净值历史记录，请先执行数据同步拉取数据")
        st.info("点击侧边栏或主页的「立即同步数据」按钮")

with tab2:
    st.markdown("#### 设置风控阈值")
    with st.form(f"risk_form_{selected.fund_code}"):
        st.markdown("##### 静态风控设置")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            stop_profit = st.number_input(
                "止盈目标浮盈率（%）",
                value=float(selected.target_stop_profit or 20.0),
                min_value=1.0, max_value=500.0, step=1.0,
                help="当浮盈率达到此值时触发静态止盈预警"
            )
        with col_r2:
            stop_loss = st.number_input(
                "绝对止损阈值（%，填负值）",
                value=float(selected.target_stop_loss or -15.0),
                min_value=-80.0, max_value=-1.0, step=1.0,
                help="当回撤幅度低于此值时触发止损预警"
            )
            
        st.markdown("##### 移动止盈 (Trailing Stop)")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            trail_start = st.number_input(
                "启动线（%）",
                value=float(selected.trailing_stop_start_pct or 10.0),
                min_value=1.0, max_value=500.0, step=1.0,
                help="利润达到多少百分比时开启移动止盈"
            )
        with col_t2:
            trail_tolerance = st.number_input(
                "回撤容忍度（%）",
                value=float(selected.trailing_stop_tolerance_pct or 5.0),
                min_value=0.1, max_value=50.0, step=0.5,
                help="从最高利润点回落多少百分比触发止盈清仓"
            )

        save_risk = st.form_submit_button("保存风控规则", type="primary")

    if save_risk:
        db = get_db_session()
        try:
            h = db.query(Holding).filter_by(fund_code=selected.fund_code).first()
            if h:
                h.target_stop_profit = Decimal(str(stop_profit))
                h.target_stop_loss   = Decimal(str(stop_loss))
                h.trailing_stop_start_pct = Decimal(str(trail_start))
                h.trailing_stop_tolerance_pct = Decimal(str(trail_tolerance))
                db.commit()
                st.success("风控规则保存成功！")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            db.rollback()
            st.error(f"保存失败：{e}")
        finally:
            db.close()


with tab3:
    st.markdown("#### 指数估值温度计")
    st.caption("为该基金绑定一个跟踪/对标的指数，系统将自动计算其历史市盈率(PE)/市净率(PB)的分位点，辅助判断当前是高估还是低估。")
    
    col_idx, _ = st.columns([1, 2])
    with col_idx:
        with st.form(f"index_form_{selected.fund_code}"):
            new_index = st.text_input(
                "绑定基准指数名称 (如: 沪深300, 中证500, 创业板指)",
                value=selected.benchmark_index or ""
            )
            save_idx = st.form_submit_button("绑定指数")
            
        if save_idx:
            db = get_db_session()
            try:
                h = db.query(Holding).filter_by(fund_code=selected.fund_code).first()
                if h:
                    h.benchmark_index = new_index.strip() if new_index else None
                    db.commit()
                    st.success(f"已绑定指数：{new_index}")
                    st.cache_data.clear()
                    st.rerun()
            except Exception as e:
                db.rollback()
                st.error(f"保存失败：{e}")
            finally:
                db.close()
                
    if selected.benchmark_index:
        st.markdown(f"**当前追踪指数：** `{selected.benchmark_index}`")
        
        @st.cache_data(ttl=3600)
        def fetch_valuation(symbol):
            try:
                import akshare as ak
                df_pe = ak.stock_index_pe_lg(symbol=symbol)
                df_pb = ak.stock_index_pb_lg(symbol=symbol)
                return df_pe, df_pb
            except Exception as e:
                return None, None
                
        with st.spinner("正在拉取历史估值数据，这可能需要几秒钟..."):
            df_pe, df_pb = fetch_valuation(selected.benchmark_index)
            
        if df_pe is not None and not df_pe.empty and df_pb is not None and not df_pb.empty:
            # PE Percentile
            pe_col = '滚动市盈率' if '滚动市盈率' in df_pe.columns else df_pe.columns[-1]
            current_pe = float(df_pe[pe_col].iloc[-1])
            pe_series = df_pe[pe_col].dropna()
            pe_percentile = (pe_series < current_pe).sum() / len(pe_series) * 100
            
            # PB Percentile
            pb_col = '滚动市净率' if '滚动市净率' in df_pb.columns else df_pb.columns[-1]
            current_pb = float(df_pb[pb_col].iloc[-1])
            pb_series = df_pb[pb_col].dropna()
            pb_percentile = (pb_series < current_pb).sum() / len(pb_series) * 100
            
            def get_eval_str(pct):
                if pct < 20: return "严重低估 (击球区)"
                elif pct < 40: return "偏低估"
                elif pct < 60: return "估值合理"
                elif pct < 80: return "偏高估"
                else: return "严重高估 (泡沫区)"
                
            st.markdown("---")
            vc1, vc2 = st.columns(2)
            with vc1:
                st.metric("滚动市盈率 (PE-TTM)", f"{current_pe:.2f}")
                st.markdown(f"**历史百分位：** `{pe_percentile:.1f}%`  ({get_eval_str(pe_percentile)})")
                # Draw a simple progress bar
                st.progress(pe_percentile / 100)
                
            with vc2:
                st.metric("市净率 (PB)", f"{current_pb:.2f}")
                st.markdown(f"**历史百分位：** `{pb_percentile:.1f}%`  ({get_eval_str(pb_percentile)})")
                st.progress(pb_percentile / 100)
                
            st.info("**操作建议参考**：百分位低于 20% 时处于极具性价比区间，适合开启定投或抄底加仓；高于 80% 时处于高估值区间，可考虑分批止盈或停止买入。")
        else:
            st.warning("拉取估值数据失败，请确认输入的指数名称是否正确（如必须为 '沪深300' 而不是 '000300'，或该指数暂无乐咕乐蜀估值数据）。")
