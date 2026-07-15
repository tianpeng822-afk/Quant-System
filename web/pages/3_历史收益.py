"""
📈 历史收益页面 — 资产净值曲线、月度收益热力图、与基准对比
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import json
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from web.utils import get_db_session, fmt_money, fmt_pct
from app.models import DailySnapshot

st.set_page_config(page_title="历史收益 · 我的基金", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)


st.markdown("# 历史收益分析")
st.caption("资产净值曲线、月度收益热力图及收益归因分析")
st.markdown("---")

# ── 加载快照数据 ────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_snapshots():
    db = get_db_session()
    try:
        snaps = (
            db.query(DailySnapshot)
            .order_by(DailySnapshot.snapshot_date.asc())
            .all()
        )
        return snaps
    finally:
        db.close()

snapshots = load_snapshots()

if not snapshots:
    st.info("暂无历史数据。请先执行数据同步至少运行两次，生成每日快照后再查看此页面。")
    st.stop()

# ── 构建 DataFrame ────────────────────────────────────────────
df = pd.DataFrame([
    {
        "date":        s.snapshot_date,
        "market_value": float(s.total_market_value or 0),
        "total_cost":   float(s.total_cost or 0),
        "total_pnl":    float(s.total_pnl or 0),
        "total_pnl_pct": float(s.total_pnl_pct or 0),
        "xirr":         float(s.portfolio_xirr or 0),
    }
    for s in snapshots
])
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

# ── 时间区间筛选 ────────────────────────────────────────────────
col_f1, col_f2 = st.columns([3, 1])
with col_f1:
    period = st.radio(
        "查看区间",
        ["近1月", "近3月", "近6月", "近1年", "全部"],
        horizontal=True,
        index=4,
    )
with col_f2:
    st.markdown("")

period_map = {"近1月": 30, "近3月": 90, "近6月": 180, "近1年": 365, "全部": 99999}
cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=period_map[period])
df_view = df[df["date"] >= cutoff].copy()

if df_view.empty:
    st.warning("所选时间段内暂无数据")
    st.stop()

# ── 期间涨跌幅 ────────────────────────────────────────────────
first_mv = df_view["market_value"].iloc[0]
last_mv  = df_view["market_value"].iloc[-1]
period_pnl_pct = ((last_mv - first_mv) / first_mv * 100) if first_mv else 0
period_pnl_abs = last_mv - first_mv

# ── 核心指标 ─────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("当前总市值",       f"¥{last_mv:,.2f}")
k2.metric(f"{period}区间收益",  fmt_money(period_pnl_abs),
          delta=f"{period_pnl_pct:+.2f}%")
k3.metric("总浮动盈亏率",      fmt_pct(df_view["total_pnl_pct"].iloc[-1]))
k4.metric("年化收益(XIRR)",    fmt_pct(df_view["xirr"].iloc[-1]) if df_view["xirr"].iloc[-1] != 0 else "计算中")

st.markdown("")

# ── 主收益曲线 ────────────────────────────────────────────────
st.markdown("### 资产净值曲线")

fig_main = go.Figure()

# 市值面积图
fig_main.add_trace(go.Scatter(
    x=df_view["date"], y=df_view["market_value"],
    name="总市值", mode="lines",
    line=dict(color="#FF4B4B", width=2.5),
    fill="tozeroy", fillcolor="rgba(255,75,75,0.08)",
    hovertemplate="日期：%{x|%Y-%m-%d}<br>总市值：¥%{y:,.2f}<extra></extra>",
))

# 投入成本线
fig_main.add_trace(go.Scatter(
    x=df_view["date"], y=df_view["total_cost"],
    name="累计投入", mode="lines",
    line=dict(color="#6699cc", width=1.5, dash="dot"),
    hovertemplate="累计投入：¥%{y:,.2f}<extra></extra>",
))

# 盈亏填充区域
fig_main.add_trace(go.Scatter(
    x=df_view["date"],
    y=df_view["total_cost"],
    showlegend=False, mode="none",
    fillcolor="rgba(0,212,170,0.05)",
))

fig_main.update_layout(
    legend=dict(orientation="h", y=1.06, x=0),
    margin=dict(l=0, r=0, t=30, b=0),
    height=350,
    xaxis=dict(showgrid=True, rangeslider=dict(visible=True, thickness=0.04)),
    yaxis=dict(showgrid=True, tickprefix="¥"),
    hovermode="x unified",
)
st.plotly_chart(fig_main, use_container_width=True)

# ── 日收益率分布 & 盈亏率趋势 ─────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.markdown("### 盈亏率趋势")
    fig_pct = go.Figure()
    colors_pct = ["#FF4B4B" if v >= 0 else "#00D4AA" for v in df_view["total_pnl_pct"]]
    fig_pct.add_trace(go.Bar(
        x=df_view["date"], y=df_view["total_pnl_pct"],
        name="盈亏率", marker_color=colors_pct,
        hovertemplate="%{x|%Y-%m-%d}<br>盈亏率：%{y:.2f}%<extra></extra>",
    ))
    fig_pct.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=260,
        yaxis=dict(ticksuffix="%"),
    )
    st.plotly_chart(fig_pct, use_container_width=True)

with col_r:
    st.markdown("### 月度收益热力图")
    df_view["year"]  = df_view["date"].dt.year
    df_view["month"] = df_view["date"].dt.month

    # 每月末收益率
    monthly = (
        df_view.groupby(["year", "month"])
        .agg(last_pnl_pct=("total_pnl_pct", "last"))
        .reset_index()
    )
    monthly["diff"] = monthly.groupby("year")["last_pnl_pct"].diff().fillna(monthly["last_pnl_pct"])

    years  = sorted(monthly["year"].unique())
    months = list(range(1, 13))
    z_data = []
    for y in years:
        row = []
        for m in months:
            val = monthly[(monthly["year"] == y) & (monthly["month"] == m)]["diff"]
            row.append(float(val.values[0]) if len(val) > 0 else None)
        z_data.append(row)

    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    fig_heat = go.Figure(go.Heatmap(
        z=z_data,
        x=month_labels,
        y=[str(y) for y in years],
        colorscale=[
            [0.0,  "#00D4AA"],
            [0.5,  "white"],
            [1.0,  "#FF4B4B"],
        ],
        zmid=0,
        text=[[f"{v:.1f}%" if v is not None else "" for v in row] for row in z_data],
        texttemplate="%{text}",
        showscale=True,
        colorbar=dict(ticksuffix="%", thickness=12),
    ))
    fig_heat.update_layout(
        margin=dict(l=0, r=40, t=10, b=0),
        height=260,
    )
    st.plotly_chart(fig_heat, use_container_width=True)

# ── 数据明细表 ────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 每日快照明细")

with st.expander("展开查看原始数据"):
    df_show = df_view[["date", "market_value", "total_cost", "total_pnl", "total_pnl_pct"]].copy()
    df_show.columns = ["日期", "总市值(元)", "累计投入(元)", "浮动盈亏(元)", "盈亏率(%)"]
    df_show["日期"] = df_show["日期"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        df_show.sort_values("日期", ascending=False),
        use_container_width=True, hide_index=True,
        column_config={
            "总市值(元)": st.column_config.NumberColumn(format="¥%.2f"),
            "累计投入(元)": st.column_config.NumberColumn(format="¥%.2f"),
            "浮动盈亏(元)": st.column_config.NumberColumn(format="¥%.2f"),
            "盈亏率(%)": st.column_config.NumberColumn(format="%.2f%%"),
        }
    )

    # CSV 导出
    csv = df_show.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出 CSV",
        data=csv.encode("utf-8-sig"),
        file_name=f"myfund_history_{date.today()}.csv",
        mime="text/csv",
    )
