"""
🏠 首页 — 投资组合总览
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from web.utils import get_db_session, fmt_money, fmt_pct, pnl_color
from app.models import Holding, DailySnapshot, Account, PendingOrder
from app.models.pending_order import PendingOrderStatus

# ── 页面配置 ──────────────────────────────────────────────────
st.set_page_config(
    page_title="我的基金 · 看板",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)



import datetime
now = datetime.datetime.now()
today = now.date()

# ── 数据加载 ──────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_dashboard_data():
    db = get_db_session()
    try:
        from app.models import NavHistory
        holdings = db.query(Holding).filter(Holding.shares > 0).all()
        accounts = db.query(Account).filter(Account.is_active == True).all()
        snapshots = (
            db.query(DailySnapshot)
            .order_by(DailySnapshot.snapshot_date.asc())
            .limit(365)
            .all()
        )
        pending_orders = db.query(PendingOrder).filter_by(status=PendingOrderStatus.PENDING).all()
        
        nav_history_dict = {}
        fund_codes = [h.fund_code for h in holdings]
        if fund_codes:
            navs = db.query(NavHistory).filter(NavHistory.fund_code.in_(fund_codes)).order_by(NavHistory.fund_code, NavHistory.nav_date.desc()).all()
            for n in navs:
                if n.fund_code not in nav_history_dict:
                    nav_history_dict[n.fund_code] = []
                if len(nav_history_dict[n.fund_code]) < 2:
                    nav_history_dict[n.fund_code].append((n.nav_date, float(n.unit_nav)))
                    
        return holdings, accounts, snapshots, pending_orders, nav_history_dict
    finally:
        db.close()

holdings_all, accounts_all, snapshots, pending_orders_all, nav_history_dict = load_dashboard_data()

# ── 侧边栏 ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 我的基金")
    st.markdown("**个人基金量化管理系统**")
    st.markdown("---")
    st.markdown("**第一版**")
    st.caption("数据每日 22:30 自动更新")
    st.markdown("---")

    st.markdown("### 账户视图切换")
    account_options = {"all": "全账户汇总"}
    for acc in accounts_all:
        account_options[acc.id] = f"{acc.name}"
    
    # Initialize session state if not exist
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
    
    if st.button("立即同步数据", use_container_width=True, type="primary"):
        with st.spinner("正在强制拉取最新净值并计算..."):
            try:
                from app.pipeline import run_daily_etl, check_ladder_triggers
                from web.utils import get_db_session
                from app.models import Holding
                
                run_daily_etl(force_refresh=True)
                st.cache_data.clear()

                # ── 阶梯止盈检查 ──────────────────────
                db_l = get_db_session()
                try:
                    ladder_holdings = db_l.query(Holding).filter(Holding.shares > 0).all()
                    ladder_result = check_ladder_triggers(ladder_holdings)
                finally:
                    db_l.close()
                
                st.success("数据同步执行完成！")
                st.rerun()
            except Exception as e:
                st.error(f"数据同步失败：{e}")

    if st.button("手动发送日报", use_container_width=True):
        with st.spinner("正在生成日报..."):
            try:
                from app.pipeline import run_daily_etl, _build_report, check_ladder_triggers
                from app.notifier.email import send_email
                from app.notifier.pushplus import send_wechat
                from app.notifier.wecom import send_wecom
                from app.config import settings
                from web.utils import get_db_session
                from app.models import Holding
                
                run_daily_etl(force_refresh=False)
                
                db = get_db_session()
                try:
                    rep_holdings = db.query(Holding).filter(Holding.shares > 0).all()
                    # 阶梯检查
                    ladder = check_ladder_triggers(rep_holdings)
                    ladder_triggers = ladder["triggers"]
                    ladder_statuses = ladder["statuses"]
                    
                    rep_mv = sum((h.market_value or Decimal("0") for h in rep_holdings), Decimal("0"))
                    rep_unrealized = sum((h.unrealized_pnl or Decimal("0") for h in rep_holdings), Decimal("0"))
                    rep_cost = sum((h.total_cost or Decimal("0") for h in rep_holdings), Decimal("0"))
                    rep_pct = (rep_unrealized / rep_cost * 100).quantize(Decimal("0.0001")) if rep_cost else Decimal("0")
                    
                    from app.models import NavHistory
                    rep_daily_pnl = Decimal("0")
                    rep_daily_pnl_by_fund: dict[str, Decimal] = {}
                    for h in rep_holdings:
                        navs = db.query(NavHistory).filter(
                            NavHistory.fund_code == h.fund_code,
                            NavHistory.nav_date <= today
                        ).order_by(NavHistory.nav_date.desc()).limit(2).all()
                        if len(navs) == 2:
                            fund_daily_pnl = (navs[0].unit_nav - navs[1].unit_nav) * h.shares
                            rep_daily_pnl += fund_daily_pnl
                            rep_daily_pnl_by_fund[h.fund_code] = fund_daily_pnl
                finally:
                    db.close()
                
                report_md = _build_report(today, rep_holdings, rep_mv, rep_unrealized, rep_pct, rep_daily_pnl, rep_daily_pnl_by_fund, ladder_triggers, ladder_statuses)
                
                title = f"📊 基金日报 {today.strftime('%Y-%m-%d')} (手动推送)"
                success = False
                
                if settings.SMTP_SERVER and settings.SMTP_USER:
                    success = send_email(title=title, content=report_md)
                
                if not success and settings.WECOM_WEBHOOK_URL:
                    success = send_wecom(content=f"# {title}\n\n{report_md}")
                    
                if not success and settings.PUSHPLUS_TOKEN:
                    success = send_wechat(title=title, content=report_md)
                
                if success:
                    st.success("日报推送成功！")
                else:
                    st.error("推送失败，请检查日志或配置。")
            except Exception as e:
                st.error(f"推送异常：{e}")


# ── 数据过滤 ──────────────────────────────────────────────────
if st.session_state.selected_account_id == "all":
    holdings = holdings_all
    pending_orders = pending_orders_all
else:
    holdings = [h for h in holdings_all if h.account_id == st.session_state.selected_account_id]
    pending_orders = [po for po in pending_orders_all if po.account_id == st.session_state.selected_account_id]

# ── 汇总计算 ──────────────────────────────────────────────────
total_mv    = sum(float(h.market_value  or 0) for h in holdings)
total_cost  = sum(float(h.total_cost    or 0) for h in holdings)
total_pnl   = sum(float(h.unrealized_pnl or 0) for h in holdings)
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
total_pending = sum(float(po.amount or 0) for po in pending_orders)
total_assets = total_mv + total_pending

daily_pnl = 0.0
daily_pnl_label = "今日盈亏"
max_nav_date = max((h.latest_nav_date for h in holdings if h.latest_nav_date is not None), default=None)

def calc_real_daily_pnl():
    pnl = 0.0
    for h in holdings:
        history = nav_history_dict.get(h.fund_code, [])
        if len(history) >= 2:
            curr_nav = history[0][1]
            prev_nav = history[1][1]
            pnl += float(h.shares) * (curr_nav - prev_nav)
    return pnl

if now.hour >= 15:
    daily_pnl_label = "今日盈亏"
    # 如果最新的净值日期已经是今天，则是真实的今日盈亏
    # 如果还没更新净值，则计算的是最近一次变动（即昨日）
    daily_pnl = calc_real_daily_pnl()
else:
    daily_pnl_label = "昨日盈亏"
    daily_pnl = calc_real_daily_pnl()

# ── 标题 ──────────────────────────────────────────────────────
st.markdown("# 投资组合总览")
last_update = snapshots[-1].snapshot_date if snapshots else date.today()
st.caption(f"最后更新：{last_update}　｜　持仓基金：{len(holdings)} 只　｜　关联账户：{len(accounts_all)} 个")
st.markdown("---")

# ── 核心指标 ──────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("总资产", f"¥{total_assets:,.2f}")
with c2:
    st.metric("累计投入", f"¥{total_cost:,.2f}")
with c3:
    st.metric("在途资金", f"¥{total_pending:,.2f}")

st.write("") # 增加行间距

c4, c5, c6 = st.columns(3)
with c4:
    delta_str = f"{fmt_pct(total_pnl_pct)}"
    st.metric("总浮动盈亏", fmt_money(total_pnl), delta=delta_str,
              delta_color="inverse")
with c5:
    st.metric(daily_pnl_label, fmt_money(daily_pnl),
              delta_color="inverse")
with c6:
    pass # 留空占位，保持左右宽度一致

st.markdown("")

# ── 资产净值曲线 & 持仓占比 ────────────────────────────────────
col_chart, col_pie = st.columns([2, 1])

with col_chart:
    st.markdown("### 资产净值曲线")
    if snapshots:
        df_snap = pd.DataFrame([
            {
                "日期": s.snapshot_date,
                "市值": float(s.total_market_value or 0),
                "投入成本": float(s.total_cost or 0),
            }
            for s in snapshots
        ])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_snap["日期"], y=df_snap["市值"],
            name="总市值", mode="lines",
            line=dict(color="#FF4B4B", width=2.5),
            fill="tozeroy", fillcolor="rgba(255,75,75,0.07)",
        ))
        fig.add_trace(go.Scatter(
            x=df_snap["日期"], y=df_snap["投入成本"],
            name="累计投入", mode="lines",
            line=dict(color="#6699cc", width=1.5, dash="dot"),
        ))
        fig.update_layout(
            legend=dict(orientation="h", y=1.08, x=0),
            margin=dict(l=0, r=0, t=30, b=0),
            height=300,
            xaxis=dict(showgrid=True),
            yaxis=dict(showgrid=True, tickprefix="¥"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无历史快照数据，请先执行数据同步")

with col_pie:
    st.markdown("### 持仓占比")
    if holdings:
        df_pie = pd.DataFrame([
            {"基金": f"{h.fund_name[:6]}\n({h.fund_code})",
             "市值": float(h.market_value or 0)}
            for h in holdings if (h.market_value or 0) > 0
        ])
        if not df_pie.empty:
            colors = ["#FF4B4B", "#3B82F6", "#F59E0B", "#00D4AA",
                      "#8B5CF6", "#EC4899", "#10B981", "#F97316"]
            fig2 = go.Figure(go.Pie(
                labels=df_pie["基金"], values=df_pie["市值"],
                hole=0.55,
                marker=dict(colors=colors[:len(df_pie)],
                            line=dict(color="#0A0E1A", width=2)),
                textinfo="percent", textfont_size=11,
            ))
            fig2.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=300,
                showlegend=True,
                legend=dict(font=dict(size=10), x=0, y=-0.1, orientation="h"),
            )
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("暂无持仓数据")

st.markdown("---")

# ── 持仓盈亏排行 ─────────────────────────────────────────────
st.markdown("### 持仓明细与盈亏排行")

if holdings:
    rows = []
    for h in sorted(holdings, key=lambda x: float(x.unrealized_pnl or 0), reverse=True):
        pnl_pct = float(h.unrealized_pnl_pct or 0)
        dd = float(h.current_drawdown or 0)

        # 风控状态标记
        risk = "正常"
        if h.target_stop_profit and pnl_pct >= float(h.target_stop_profit):
            risk = "止盈预警"
        if h.target_stop_loss and pnl_pct <= float(h.target_stop_loss):
            risk = "加倍定投触发"
            if h.dca_enabled and h.dynamic_dca_enabled:
                from app.pipeline import get_dca_deduction_rate
                rate = get_dca_deduction_rate(pnl_pct)
                risk = f"定投 ×{rate:.1f}倍"

        rows.append({
            "基金代码": h.fund_code,
            "基金名称": h.fund_name,
            "持有份额": f"{float(h.shares):,.2f}",
            "最新净值": f"{float(h.latest_nav or 0):.4f}",
            "当前市值": f"¥{float(h.market_value or 0):,.2f}",
            "均价成本": f"{float(h.avg_cost_price or 0):.4f}",
            "浮动盈亏": fmt_money(h.unrealized_pnl),
            "盈亏率": fmt_pct(h.unrealized_pnl_pct),
            "当前回撤": fmt_pct(h.current_drawdown),
            "风控状态": risk,
        })

    df_holdings = pd.DataFrame(rows)
    st.dataframe(df_holdings, use_container_width=True, hide_index=True,
                 column_config={
                     "盈亏率": st.column_config.TextColumn("盈亏率"),
                     "当前回撤": st.column_config.TextColumn("当前回撤"),
                 })

    # 盈亏率横向条形图
    st.markdown("#### 各基金浮盈率对比")
    df_bar = pd.DataFrame([
        {"基金": f"{h.fund_name[:8]}({h.fund_code})",
         "浮盈率(%)": float(h.unrealized_pnl_pct or 0)}
        for h in sorted(holdings, key=lambda x: float(x.unrealized_pnl_pct or 0), reverse=True)
    ])
    bar_colors = ["#FF4B4B" if v >= 0 else "#00D4AA" for v in df_bar["浮盈率(%)"]]
    fig3 = go.Figure(go.Bar(
        x=df_bar["浮盈率(%)"], y=df_bar["基金"],
        orientation="h", marker_color=bar_colors,
        text=[f"{v:+.2f}%" for v in df_bar["浮盈率(%)"]],
        textposition="outside",
    ))
    fig3.update_layout(
        margin=dict(l=0, r=60, t=10, b=0),
        height=max(200, len(df_bar) * 50),
        xaxis=dict(ticksuffix="%"),
    )
    st.plotly_chart(fig3, use_container_width=True)

    # ── 定投计划 ─────────────────────────────────────────────
    dca_holdings = [h for h in holdings if h.dca_weekly_amount and float(h.dca_weekly_amount) > 0]
    if dca_holdings:
        st.markdown("---")
        st.markdown("### 每周定投计划")
        dca_rows = []
        total_weekly = 0
        for h in dca_holdings:
            weekly = float(h.dca_weekly_amount)
            total_weekly += weekly
            smart = "涨跌幅动态" if h.dynamic_dca_enabled else "固定金额"
            dca_rows.append({
                "基金": f"{h.fund_name}（{h.fund_code}）",
                "基础金额/周": f"¥{weekly:,.0f}",
                "模式": smart,
                "扣款率范围": "50%~200%自动" if h.dynamic_dca_enabled else "100%固定",
            })
        # 添加合计行
        dca_rows.append({
            "基金": "**合计**",
            "基础金额/周": f"**¥{total_weekly:,.0f}**",
            "模式": "",
            "扣款率范围": f"月投 ¥{total_weekly*4.33:,.0f}",
        })
        st.dataframe(pd.DataFrame(dca_rows), use_container_width=True, hide_index=True)
    
    paused_holdings = [h for h in holdings if h.dca_weekly_amount is not None and float(h.dca_weekly_amount) == 0 and h.dca_enabled == False]
    if paused_holdings:
        paused_info = "、".join([f"{h.fund_name}" for h in paused_holdings])
        st.caption(f"暂停定投：{paused_info}（等待行情信号）")

    # ── 阶梯止盈监控 ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 阶梯止盈监控 (20%→卖20%, 35%→卖20%, 50%→卖20%, 65%→卖30%)")

    import json, os as _os
    state_file = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data", "ladder_state.json")
    try:
        with open(state_file) as f:
            ladder_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        ladder_state = {}

    ladder_rows = []
    ladder_triggers = []

    for h in holdings:
        shares = float(h.shares or 0)
        cost = float(h.total_cost or 0)
        nav = float(h.latest_nav or 0)
        if shares <= 0 or cost <= 0:
            continue

        mv = shares * nav
        pp = (mv - cost) / cost * 100

        ls = ladder_state.get(h.fund_code, {"triggered": []})
        triggered = ls.get("triggered", [])

        # Build marks
        LEVEL_STRS = ["+20%", "+35%", "+50%", "+65%"]
        LEVEL_SELLS = [0.20, 0.20, 0.20, 0.30]
        marks_parts = []
        for i in range(4):
            marks_parts.append("✅" if i in triggered else "◻")

        next_idx = len(triggered)
        if next_idx < 4:
            avg = cost / shares
            target_nav = avg * (1 + LEVEL_SELLS[next_idx] if next_idx < 4 else 0)
            # Correct: threshold is LEVELS tuple
            threshold = 0.20 if next_idx == 0 else 0.35 if next_idx == 1 else 0.50 if next_idx == 2 else 0.65
            target_nav = avg * (1 + threshold)
            gap = threshold * 100 - pp
            next_str = f"{LEVEL_STRS[next_idx]}→卖{int(LEVEL_SELLS[next_idx]*100)}%"
            trigger_str = f"¥{target_nav:.4f} (差{gap:+.1f}%)"
            if gap <= 3:
                next_str = f"⚠️ {next_str}"
        else:
            next_str = "全部触发 (等重置<5%)"
            trigger_str = "—"

        ladder_rows.append({
            "基金": f"{h.fund_name} ({h.fund_code})",
            "阶梯": " ".join(marks_parts),
            "浮盈": f"{pp:+.1f}%",
            "下一档": next_str,
            "触发NAV": trigger_str,
        })

        # Check for new triggers (for display, state already saved by check_ladder_triggers)
        level_matches = []
        for i, th in enumerate([0.20, 0.35, 0.50, 0.65]):
            if i not in triggered and pp >= th * 100:
                level_matches.append(LEVEL_STRS[i])
        if level_matches:
            remaining = 1.0
            total_sell = 0.0
            for i, th in enumerate([0.20, 0.35, 0.50, 0.65]):
                if i not in triggered and pp >= th * 100:
                    total_sell += shares * remaining * LEVEL_SELLS[i] * nav
                    remaining *= (1 - LEVEL_SELLS[i])
            ladder_triggers.append({
                "name": h.fund_name, "code": h.fund_code,
                "levels": level_matches, "amount": total_sell,
                "nav": nav,
            })

    if ladder_triggers:
        st.error("⚠️ 以下基金触发阶梯止盈，请操作卖出：")
        for t in ladder_triggers:
            st.markdown(
                f"- **{t['name']}** ({t['code']}): 触发 {', '.join(t['levels'])} 档, "
                f"建议卖出 **¥{t['amount']:,.2f}** @ NAV ¥{t['nav']:.4f}"
            )
        st.markdown("---")

    if ladder_rows:
        st.dataframe(pd.DataFrame(ladder_rows), use_container_width=True, hide_index=True)
        st.caption("◻未触发  ✅已触发  |  浮盈<5%时自动重置所有阶梯")

else:
    st.info("暂无持仓数据，请前往「流水录入」页面添加您的第一笔申购记录")
