"""
📋 流水录入页面 — 申购 / 赎回 / 分红 流水管理
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import date
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd
import streamlit as st

from web.utils import get_db_session, fmt_money
from app.models import Account, Holding, Transaction, TransactionType
from app.models.transaction import TransactionType
from app.models.pending_order import PendingOrder

@st.cache_data(ttl=86400)
def fetch_fund_name_map():
    import json
    from pathlib import Path
    data_file = Path(__file__).resolve().parent.parent.parent / "data" / "fund_names.json"
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # Fallback to akshare if file missing
    try:
        df = ak.fund_name_em()
        return dict(zip(df["基金代码"], df["基金简称"]))
    except Exception:
        return {}


st.set_page_config(page_title="流水录入 · 我的基金", layout="wide")
st.markdown(
    '<script>document.documentElement.lang = "zh-CN"</script>',
    unsafe_allow_html=True,
)


st.markdown("# 流水录入")
st.caption("记录每一笔申购、赎回、分红操作，系统自动更新持仓成本与份额")
st.markdown("---")

# ── 加载账户列表 ──────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_accounts():
    db = get_db_session()
    try:
        return db.query(Account).filter(Account.is_active == True).all()
    finally:
        db.close()

accounts = load_accounts()
account_map = {a.name: a for a in accounts}

col_form, col_history = st.columns([1, 1])

# ══════════════════════════════════════════════
# 左列：录入表单
# ══════════════════════════════════════════════
with col_form:
    st.markdown("### 新建流水")
    
    tab_normal, tab_pending = st.tabs(["普通流水录入", "待确认定投（盲跑）"])
    
    with tab_normal:
        blind_buy = st.checkbox(
            "盲买模式（仅输入金额，等净值出来后自动确认份额）",
            value=False,
            help="适用于当日买入但净值尚未公布的情况，系统会在净值发布后自动计算份额"
        )

        with st.form("tx_form", clear_on_submit=True):
            account_name = st.selectbox(
                "选择账户 *",
                options=list(account_map.keys()),
                help="选择本次交易所属账户"
            )

            tx_type_labels = {
                "申购（买入）":         TransactionType.BUY,
                "赎回（卖出）":         TransactionType.SELL,
                "分红派现":            TransactionType.DIVIDEND_CASH,
                "红利再投（转份额）":   TransactionType.DIVIDEND_REINVEST,
                "转入":                TransactionType.TRANSFER_IN,
                "转出":                TransactionType.TRANSFER_OUT,
            }
            tx_label = st.selectbox("流水类型 *", options=list(tx_type_labels.keys()))
            tx_type  = tx_type_labels[tx_label]

            col1, col2 = st.columns(2)
            with col1:
                fund_code = st.text_input("基金代码 *", placeholder="如：110022", max_chars=8)
            with col2:
                fund_name = st.text_input("基金名称", placeholder="选填，留空将自动拉取")

            col3, col4 = st.columns(2)
            with col3:
                trade_date = st.date_input("交易日期 *", value=date.today(), max_value=date.today())
            with col4:
                confirm_date = st.date_input("份额确认日", value=None)

            if blind_buy:
                col5, col6 = st.columns(2)
                with col5:
                    gross_amount = st.number_input(
                        "总扣款金额（含手续费）*", min_value=0.01, value=1000.00,
                        step=100.0, format="%.2f", key="gross_amount",
                        help="实际扣款金额，包括手续费"
                    )
                with col6:
                    fee_rate = st.number_input(
                        "手续费率 (%)", min_value=0.0, value=0.15,
                        step=0.01, format="%.2f", key="fee_rate",
                        help="申购费率，默认0.15%（平台优惠后）"
                    )
                st.info(f"盲买模式：已扣款 ¥{gross_amount:,.2f}，等净值出来后自动确认份额")
            else:
                col5, col6 = st.columns(2)
                with col5:
                    nav_price = st.number_input(
                        "成交净值（元/份）*", min_value=0.0001, value=1.0000,
                        step=0.0001, format="%.4f"
                    )
                with col6:
                    shares = st.number_input(
                        "变动份额 *", min_value=0.0001, value=100.0000,
                        step=0.01, format="%.4f",
                        help="买入填正数；赎回填实际赎回份额（系统自动处理正负）"
                    )

                col7, col8 = st.columns(2)
                with col7:
                    fee = st.number_input(
                        "手续费（元）", min_value=0.0, value=0.0,
                        step=0.01, format="%.2f"
                    )

                gross = shares * nav_price + fee
                net   = shares * nav_price
                st.info(f"预计扣款：**¥{gross:,.2f}** ｜ 净额：**¥{net:,.2f}** ｜ 手续费：**¥{fee:.2f}**")

            fund_category = st.selectbox(
                "资产类别（可选）",
                options=["", "A股/宽基", "A股/消费", "A股/科技", "A股/医疗",
                         "美股/科技", "港股", "债券/纯债", "债券/可转债", "商品/黄金", "其他"],
                key="fund_category_outside"
            )

            memo = st.text_input("备注（可选）", placeholder="如：首次定投、止盈减仓...")

            submitted = st.form_submit_button("提交流水", type="primary", use_container_width=True)

            # ── 表单提交处理 ─────────────────────────────────────────
            if submitted:
                errors = []
                if not fund_code or len(fund_code) != 6:
                    errors.append("基金代码必须为 6 位")
                if not fund_name and fund_code and len(fund_code) == 6:
                    fund_name = fetch_fund_name_map().get(fund_code, "")
                if not fund_name:
                    errors.append("无法自动拉取该基金名称，请手动填写")
                if account_name not in account_map:
                    errors.append("请选择有效账户")

                if errors:
                    for e in errors:
                        st.error(f"{e}")
                else:
                    db = get_db_session()
                    try:
                        account = account_map[account_name]

                        if blind_buy:
                            from app.models.transaction import TransactionStatus
                            gross_dec = Decimal(str(gross_amount))
                            fee_rate_dec = Decimal(str(fee_rate))

                            tx = Transaction(
                                account_id=account.id,
                                fund_code=fund_code,
                                fund_name=fund_name,
                                tx_type=TransactionType.BUY,
                                status=TransactionStatus.PENDING,
                                trade_date=trade_date,
                                amount=gross_dec,
                                fee=None,
                                net_amount=None,
                                shares=None,
                                nav_price=None,
                                source="手动录入-盲买",
                                memo=f"盲买：扣款¥{gross_amount:.2f}，费率{fee_rate}%" if not memo else memo,
                            )
                            db.add(tx)
                            db.commit()
                            st.success(f"盲买流水录入成功！{fund_code} · 待确认 · ¥{gross_amount:.2f}")
                        else:
                            shares_dec    = Decimal(str(shares))
                            nav_dec       = Decimal(str(nav_price))
                            fee_dec       = Decimal(str(fee))
                            gross_dec     = (shares_dec * nav_dec + fee_dec).quantize(Decimal("0.01"))
                            net_dec       = (shares_dec * nav_dec).quantize(Decimal("0.01"))

                            if tx_type in (TransactionType.SELL, TransactionType.TRANSFER_OUT):
                                shares_dec = -abs(shares_dec)

                            holding = (
                                db.query(Holding)
                                .filter_by(account_id=account.id, fund_code=fund_code)
                                .first()
                            )
                            if holding is None:
                                holding = Holding(
                                    account_id=account.id,
                                    fund_code=fund_code,
                                    fund_name=fund_name,
                                    fund_category=fund_category or None,
                                    shares=Decimal("0"),
                                    avg_cost_price=Decimal("0"),
                                    total_cost=Decimal("0"),
                                )
                                db.add(holding)
                                db.flush()

                            tx = Transaction(
                                account_id=account.id,
                                holding_id=holding.id,
                                fund_code=fund_code,
                                fund_name=fund_name,
                                tx_type=tx_type,
                                trade_date=trade_date,
                                confirm_date=confirm_date,
                                shares=shares_dec,
                                nav_price=nav_dec,
                                amount=gross_dec,
                                fee=fee_dec,
                                net_amount=net_dec,
                                source="手动录入",
                                memo=memo or None,
                            )
                            db.add(tx)
                            db.flush()
                            
                            from app.engine.recalc import recalculate_holding_costs
                            recalculate_holding_costs(db, holding)

                            db.commit()
                            st.success(f"流水录入成功！{tx_label} {fund_code} · {shares:.4f} 份 · ¥{gross:.2f}")

                        st.cache_data.clear()

                    except Exception as e:
                        db.rollback()
                        st.error(f"录入失败：{e}")
                    finally:
                        db.close()


    with tab_pending:
        with st.form("pending_form", clear_on_submit=True):
            p_account_name = st.selectbox(
                "选择账户 *",
                options=list(account_map.keys()),
                help="选择本次定投所属账户",
                key="p_account"
            )

            col1, col2 = st.columns(2)
            with col1:
                p_fund_code = st.text_input("基金代码 *", placeholder="如：110022", max_chars=8)
            with col2:
                p_fund_name = st.text_input("基金名称", placeholder="选填，留空将自动拉取")

            col3, col4 = st.columns(2)
            with col3:
                p_trade_date = st.date_input("扣款日期 *", value=date.today(), max_value=date.today(), key="p_date")
            with col4:
                p_fee_rate = st.number_input(
                    "买入费率 (%) *", min_value=0.0, value=0.15,
                    step=0.01, format="%.2f", key="p_fee",
                    help="公募标准通常打一折即 0.15%。系统自动计算扣费。"
                )

            p_amount = st.number_input(
                "总扣款金额（元）*", min_value=0.01, value=1000.00,
                step=100.0, format="%.2f", key="p_amount"
            )

            p_memo = st.text_input("备注（可选）", placeholder="如：周定投", key="p_memo")

            p_submitted = st.form_submit_button("提交定投计划", type="primary", use_container_width=True)

        if p_submitted:
            p_errors = []
            if not p_fund_code or len(p_fund_code) != 6:
                p_errors.append("基金代码必须为 6 位")
            if not p_fund_name and p_fund_code and len(p_fund_code) == 6:
                p_fund_name = fetch_fund_name_map().get(p_fund_code, "")
            if not p_fund_name:
                p_errors.append("无法自动拉取该基金名称，请手动填写")
            if p_account_name not in account_map:
                p_errors.append("请选择有效账户")

            if p_errors:
                for e in p_errors:
                    st.error(f"{e}")
            else:
                db = get_db_session()
                try:
                    p_account = account_map[p_account_name]
                    pending = PendingOrder(
                        account_id=p_account.id,
                        fund_code=p_fund_code,
                        fund_name=p_fund_name,
                        trade_date=p_trade_date,
                        amount=Decimal(str(p_amount)),
                        fee_rate=Decimal(str(p_fee_rate)),
                        memo=p_memo or None,
                    )
                    db.add(pending)
                    db.commit()
                    st.success(f"定投已挂单！等今晚出净值后，系统会自动算份额入库！")
                    st.cache_data.clear()
                except Exception as e:
                    db.rollback()
                    st.error(f"录入失败：{e}")
                finally:
                    db.close()

# ══════════════════════════════════════════════
# 右列：历史流水
# ══════════════════════════════════════════════
with col_history:
    # ── 待确认订单（定投 + 盲买）─────────────────────────────
    db = get_db_session()
    try:
        from app.models.transaction import TransactionStatus
        
        pending_list = db.query(PendingOrder).filter(PendingOrder.status == 'pending').all()
        pending_txs = db.query(Transaction).filter(
            Transaction.status == TransactionStatus.PENDING
        ).all()
        
        if pending_list or pending_txs:
            st.markdown("### 待确认订单")
            
            if pending_list:
                st.markdown("**待确认定投**")
                p_rows = []
                for p in pending_list:
                    p_rows.append({
                        "日期": str(p.trade_date),
                        "基金": f"{p.fund_name}({p.fund_code})",
                        "扣款总额": f"¥{float(p.amount):.2f}",
                        "费率": f"{float(p.fee_rate):.2f}%",
                        "类型": "定投",
                        "状态": "等待净值公布..."
                    })
                st.dataframe(p_rows, use_container_width=True, hide_index=True)
            
            if pending_txs:
                st.markdown("**待确认盲买**")
                t_rows = []
                for t in pending_txs:
                    t_rows.append({
                        "日期": str(t.trade_date),
                        "基金": f"{t.fund_name}({t.fund_code})",
                        "扣款总额": f"¥{float(t.amount):.2f}",
                        "费率": "从备注提取" if t.memo and "费率" in t.memo else "默认0.15%",
                        "类型": "盲买",
                        "状态": "等待净值公布..."
                    })
                st.dataframe(t_rows, use_container_width=True, hide_index=True)
            
            st.markdown("---")
    finally:
        db.close()

    st.markdown("### 历史流水记录")

    db = get_db_session()
    try:
        txs = (
            db.query(Transaction)
            .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
            .limit(50)
            .all()
        )
    finally:
        db.close()

    type_emoji = {
        "buy": "申购",
        "sell": "赎回",
        "dividend_cash": "分红",
        "dividend_reinvest": "红利再投",
        "transfer_in": "转入",
        "transfer_out": "转出",
    }

    if txs:
        rows = []
        for t in txs:
            status_label = "待确认" if t.status == TransactionStatus.PENDING else "已确认"
            shares_str = f"{float(t.shares):+.4f}" if t.shares else "待确认"
            nav_str = f"{float(t.nav_price):.4f}" if t.nav_price else "待确认"
            fee_str = f"¥{float(t.fee):.2f}" if t.fee else "待确认"
            
            rows.append({
                "日期":     str(t.trade_date),
                "类型":     type_emoji.get(t.tx_type.value, t.tx_type.value),
                "基金":     f"{t.fund_name[:8]}({t.fund_code})",
                "份额":     shares_str,
                "净值":     nav_str,
                "金额":     f"¥{float(t.amount):,.2f}",
                "手续费":   fee_str,
                "状态":     status_label,
                "备注":     t.memo or "",
            })
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            height=600,
        )
        
        st.markdown("---")
        st.markdown("### 删除错误流水")
        st.caption("删除后会自动回滚关联的持仓份额和成本")
        
        tx_options = {f"[{str(t.trade_date)}] {type_emoji.get(t.tx_type.value, t.tx_type.value)} - {t.fund_name} ({float(t.shares):+.2f}份)": t.id for t in txs}
        selected_tx_label = st.selectbox("选择要删除的流水记录", options=list(tx_options.keys()))
        
        if st.button("确认删除", type="primary"):
            tx_id = tx_options[selected_tx_label]
            db = get_db_session()
            try:
                tx_to_delete = db.query(Transaction).get(tx_id)
                if tx_to_delete is None:
                    st.error("该流水记录不存在")
                else:
                    holding_id = tx_to_delete.holding_id
                    db.delete(tx_to_delete)
                    db.flush()
                    
                    if holding_id:
                        holding = db.query(Holding).get(holding_id)
                        if holding:
                            from app.engine.recalc import recalculate_holding_costs
                            recalculate_holding_costs(db, holding)
                            
                    db.commit()
                    st.success(f"流水记录已删除！")
                    st.cache_data.clear()
                    st.rerun()
            except Exception as e:
                db.rollback()
                st.error(f"删除失败：{e}")
            finally:
                db.close()
                
    else:
        st.info("暂无流水记录，请使用左侧表单录入第一笔交易")
