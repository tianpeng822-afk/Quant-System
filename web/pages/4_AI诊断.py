import streamlit as st
from app.database import SessionLocal
from app.models.holding import Holding
from app.ai.deepseek import call_deepseek_diagnose
from app.scraper.fund_rank import fetch_top_funds

st.set_page_config(page_title="DeepSeek AI 诊断", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)


st.title("DeepSeek AI 智能诊断大脑")
st.markdown("通过全市场同类数据比对与大模型逻辑推理，为你的持仓“把脉”并输出调仓建议。")

db = SessionLocal()
try:
    holdings = db.query(Holding).all()
finally:
    db.close()

if not holdings:
    st.info("当前没有持仓记录，无法进行诊断。")
    st.stop()

# 提取持仓列表供用户选择
holding_options = {f"{h.fund_name} ({h.fund_code}) [当前回撤: {h.current_drawdown or 0:.2f}%]": h for h in holdings}
selected_holding_name = st.selectbox("选择需要诊断的持仓基金：", list(holding_options.keys()))

selected_holding = holding_options[selected_holding_name]

if st.button("呼叫 DeepSeek 开始深度诊断", type="primary"):
    with st.spinner("正在根据你持有基金的【同分类】拉取高维度稳定性排行..."):
        # 传入目标基金代码，触发同类过滤和综合评分算法
        top_funds = fetch_top_funds(target_fund_code=selected_holding.fund_code, limit=10)
    
    if not top_funds:
        st.error("拉取排行数据失败，无法提供诊断。")
    else:
        with st.spinner("正在唤醒 DeepSeek 分析诊断..."):
            report = call_deepseek_diagnose(
                fund_name=selected_holding.fund_name,
                fund_code=selected_holding.fund_code,
                drawdown=float(selected_holding.current_drawdown or 0.0),
                top_funds=top_funds
            )
        
        st.success("诊断完成！")
        st.markdown("---")
        st.markdown(report)

