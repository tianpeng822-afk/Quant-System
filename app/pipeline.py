"""
ETL 主流水线（Phase 1 MVP）
────────────────────────────────────────────────
每日 22:30 由调度器触发，执行完整的 ETL 流程：
  1. 拉取所有持仓基金最新净值
  2. 刷新 holdings 表市值与盈亏
  3. 生成每日快照写入 daily_snapshots
  4. 格式化日报发送微信推送
"""

import json
import os
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Holding, DailySnapshot, Transaction, TransactionType
from app.models.pending_order import PendingOrder, PendingOrderStatus
from app.models.transaction import TransactionStatus
from app.scraper.nav_fetcher import fetch_fund_nav, update_holding_market_value, fetch_fund_nav_for_date
from app.notifier.pushplus import send_wechat
from app.notifier.wecom import send_wecom
from app.notifier.email import send_email


def get_dca_deduction_rate(pnl_pct: float) -> float:
    """支付宝涨跌幅定投扣款率

    根据当前盈亏率（净值相对平均持仓成本）返回扣款率。
    盈利越高扣款越少（止盈减投），亏损越大扣款越多（底部加仓）。

    参数
    ----
    pnl_pct : float  盈亏率（%），正数=盈利，负数=亏损

    返回
    ----
    float  扣款率，范围 0.50 ~ 2.00
    """
    # 盈利区间：扣款率递减
    if pnl_pct >= 25:
        return 0.50
    if pnl_pct >= 20:
        return 0.525
    if pnl_pct >= 15:
        return 0.55
    if pnl_pct >= 10:
        return 0.60
    if pnl_pct >= 7.5:
        return 0.70
    if pnl_pct >= 5:
        return 0.80
    if pnl_pct >= 2.5:
        return 0.90
    # 平衡区间：正常扣款
    if pnl_pct >= -2.5:
        return 1.00
    # 亏损区间：扣款率递增
    if pnl_pct >= -5:
        return 1.20
    if pnl_pct >= -7.5:
        return 1.40
    if pnl_pct >= -10:
        return 1.60
    if pnl_pct >= -15:
        return 1.80
    if pnl_pct >= -20:
        return 1.90
    if pnl_pct >= -25:
        return 1.95
    return 2.00


def auto_create_dca_orders(db: Session, today: date) -> list[PendingOrder]:
    """自动创建定投待确认订单

    检查所有启用了定投的持仓，如果今天是设定的定投日，
    则根据动态扣款率计算实际扣款金额并创建 PendingOrder。
    同一基金同一天不会重复创建。

    返回
    ----
    list[PendingOrder]  本次新创建的订单列表
    """
    weekday = today.weekday()  # 0=周一, 6=周日
    created: list[PendingOrder] = []

    holdings = (
        db.query(Holding)
        .filter(
            Holding.shares > 0,
            Holding.dca_enabled == True,
            Holding.dca_day_of_week == weekday,
        )
        .all()
    )

    if not holdings:
        return created

    for h in holdings:
        # 检查当天是否已有该基金的待确认订单（避免重复创建）
        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.fund_code == h.fund_code,
                PendingOrder.trade_date == today,
            )
            .first()
        )
        if existing:
            logger.info("[定投] {} {} 已有 {} 的待确认订单，跳过", h.fund_code, h.fund_name, today)
            continue

        base_amount = float(h.dca_weekly_amount or 0)
        if base_amount <= 0:
            continue

        if h.dynamic_dca_enabled:
            # 支付宝口径：用 T-1 净值计算盈亏率（扣款前一日净值）
            t1_nav = db.query(NavHistory).filter(
                NavHistory.fund_code == h.fund_code
            ).order_by(NavHistory.nav_date.desc()).offset(1).limit(1).first()
            if t1_nav and h.avg_cost_price and float(h.avg_cost_price) > 0:
                pnl_pct = (float(t1_nav.unit_nav) - float(h.avg_cost_price)) / float(h.avg_cost_price) * 100
            else:
                pnl_pct = float(h.unrealized_pnl_pct or 0)
            rate = get_dca_deduction_rate(pnl_pct)
        else:
            rate = 1.0

        actual_amount = round(base_amount * rate, 2)

        order = PendingOrder(
            account_id=h.account_id,
            fund_code=h.fund_code,
            fund_name=h.fund_name,
            trade_date=today,
            amount=Decimal(str(actual_amount)),
            fee_rate=h.dca_fee_rate,
            memo=f"系统自动定投(基础¥{base_amount:.0f}×{rate:.2f})",
        )
        db.add(order)
        created.append(order)
        logger.info(
            "[定投] 自动创建订单: {} {} @{} 金额 ¥{} (基础¥{}×{:.2f})",
            h.fund_code, h.fund_name, today, actual_amount, base_amount, rate,
        )

    if created:
        db.commit()
        logger.info("[定投] 本次共创建 {} 条定投订单", len(created))

    return created


# ── 阶梯止盈配置 ──────────────────────────────────────────────────
LADDER_LEVELS = [
    (0.25, 0.20),   # +25% → 卖 20%
    (0.40, 0.20),   # +40% → 卖 20%
    (0.60, 0.20),   # +60% → 卖 20%
    (0.95, 0.15),   # +95% → 卖 15%  (留15%给第五层)
    (1.50, 0.25),   # +150% → 卖 25%
]
LADDER_RESET_BELOW = 0.05
LADDER_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ladder_state.json")


def _load_ladder_state() -> dict:
    try:
        with open(LADDER_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_ladder_state(state: dict) -> None:
    os.makedirs(os.path.dirname(LADDER_STATE_FILE), exist_ok=True)
    with open(LADDER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def check_ladder_triggers(holdings: list[Holding]) -> dict:
    """检查阶梯止盈触发状态。

    Returns:
        {'triggers': [...], 'statuses': [...]}
    """
    state = _load_ladder_state()
    triggers = []
    statuses = []

    for h in holdings:
        code = h.fund_code
        shares = float(h.shares or 0)
        cost = float(h.total_cost or 0)
        nav = float(h.latest_nav or 0)
        if shares <= 0 or cost <= 0 or nav <= 0:
            continue

        mv = shares * nav
        pp = (mv - cost) / cost * 100

        # 初始化状态
        if code not in state:
            state[code] = {"triggered": [], "last_reset": None}

        st = state[code]

        # 重置检查
        if pp < LADDER_RESET_BELOW * 100:
            if st["triggered"]:
                st["triggered"] = []
                st["last_reset"] = str(date.today())
                logger.info(f"[Ladder] {code} {h.fund_name} 浮盈 {pp:+.2f}% < 5%, 阶梯已重置")

        triggered = list(st.get("triggered", []))

        # 检查新触发
        new_triggers = []
        for idx, (th, sr) in enumerate(LADDER_LEVELS):
            if idx not in triggered and pp >= th * 100:
                triggered.append(idx)
                new_triggers.append(idx)

        if new_triggers:
            st["triggered"] = triggered
            # 累积计算卖出份额
            remaining_sr = 1.0
            total_out = 0.0
            for idx_sell in new_triggers:
                sell_sr = LADDER_LEVELS[idx_sell][1]
                sell_amount = shares * remaining_sr * sell_sr * nav
                remaining_sr *= (1 - sell_sr)
                total_out += sell_amount

            triggers.append({
                "code": code,
                "name": h.fund_name,
                "new_levels": [int(LADDER_LEVELS[i][0] * 100) for i in new_triggers],
                "nav": round(nav, 4),
                "pp": round(pp, 2),
                "sell_amount": round(total_out, 2),
                "sell_shares": round(shares * (1 - remaining_sr), 2),
            })
            logger.info(f"[Ladder] {code} {h.fund_name} 触发 {[f'+{t}%' for t in [int(LADDER_LEVELS[i][0]*100) for i in new_triggers]]}, 建议卖出 ¥{total_out:,.0f}")

        # 状态摘要
        next_idx = len(triggered)
        status = {
            "code": code,
            "name": h.fund_name,
            "shares": round(shares, 2),
            "cost": round(cost, 2),
            "nav": round(nav, 4),
            "pp": round(pp, 2),
            "triggered": triggered,
            "next_level": next_idx,
        }
        if next_idx < len(LADDER_LEVELS):
            avg = cost / shares if shares else 0
            next_th = LADDER_LEVELS[next_idx][0]
            status["target_nav"] = round(avg * (1 + next_th), 4)
            status["gap_pct"] = round(next_th * 100 - pp, 2)
        statuses.append(status)

    _save_ladder_state(state)
    return {"triggers": triggers, "statuses": statuses}


def update_fund_names_cache():
    import akshare as ak
    import json
    from pathlib import Path
    try:
        df = ak.fund_name_em()
        if df is not None and not df.empty:
            name_map = dict(zip(df["基金代码"], df["基金简称"]))
            
            # Add HK funds
            try:
                df_hk = ak.fund_hk_rank_em()
                hk_map = dict(zip(df_hk["基金代码"], df_hk["基金简称"]))
                name_map.update(hk_map)
            except Exception as e:
                logger.error("Failed to fetch HK rank for name map: {}", e)

            data_dir = Path(__file__).resolve().parent.parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            file_path = data_dir / "fund_names.json"
            with open(file_path, "w", encoding="utf-8") as f:                json.dump(name_map, f, ensure_ascii=False, indent=2)
            logger.info("Updated local fund names cache ({} funds).", len(name_map))
    except Exception as e:
        logger.error("Failed to update fund names cache: {}", e)

def run_daily_etl(force_refresh: bool = False) -> None:
    """每日 ETL 主函数，被调度器调用"""
    logger.info("========== 每日 ETL 启动 (force_refresh={}) ==========", force_refresh)
    db: Session = SessionLocal()

    try:
        today = date.today()
        
        # ── Step -1: 更新本地基金名称缓存 ─────────────────────────
        update_fund_names_cache()

        # ── Step -0.5: 自动创建今日定投订单 ──────────────────────
        auto_create_dca_orders(db, today)

        # ── Step 0: 处理待确认定投订单 ─────────────────────────
        pending_orders = db.query(PendingOrder).filter(
            PendingOrder.status == PendingOrderStatus.PENDING,
            PendingOrder.trade_date <= today
        ).all()
        
        for order in pending_orders:
            nav_record = fetch_fund_nav_for_date(order.fund_code, order.trade_date, db)
            # 只有当拉取到的净值日期 大于等于 订单设定的交易日，才认为净值已出
            # (严格来说应该是等于，但考虑到周末顺延情况，至少要 >=)
            if nav_record and nav_record.unit_nav and nav_record.nav_date >= order.trade_date:
                # 净值已出，进行折算和交割
                net_amount = (order.amount / (1 + order.fee_rate / 100)).quantize(Decimal("0.01"))
                fee_amount = order.amount - net_amount
                shares = (net_amount / nav_record.unit_nav).quantize(Decimal("0.0001"))
                
                # 查找或创建持仓
                holding = db.query(Holding).filter_by(account_id=order.account_id, fund_code=order.fund_code).first()
                if not holding:
                    holding = Holding(
                        account_id=order.account_id,
                        fund_code=order.fund_code,
                        fund_name=order.fund_name,
                        shares=Decimal("0"),
                        avg_cost_price=Decimal("0"),
                        total_cost=Decimal("0"),
                    )
                    db.add(holding)
                    db.flush()
                
                # 更新持仓
                new_cost = holding.total_cost + order.amount
                new_shares = holding.shares + shares
                holding.total_cost = new_cost
                holding.shares = new_shares
                if new_shares > 0:
                    holding.avg_cost_price = (new_cost / new_shares).quantize(Decimal("0.0001"))
                
                # 创建正式流水
                tx = Transaction(
                    account_id=order.account_id,
                    holding_id=holding.id,
                    fund_code=order.fund_code,
                    fund_name=order.fund_name,
                    tx_type=TransactionType.BUY,
                    trade_date=order.trade_date,
                    confirm_date=nav_record.nav_date, # AkShare 返回的一般就是真实确认日净值
                    shares=shares,
                    nav_price=nav_record.unit_nav,
                    amount=order.amount,
                    fee=fee_amount,
                    net_amount=net_amount,
                    source="系统定投交割",
                    memo=order.memo,
                )
                db.add(tx)
                
                # 标记订单完成
                order.status = PendingOrderStatus.COMPLETED
                logger.info("定投交割完成: fund={} date={} shares={}", order.fund_code, order.trade_date, shares)
        db.commit()

        # ── Step 0.5: 处理待确认手动录入流水（盲买）───────────────
        pending_txs = db.query(Transaction).filter(
            Transaction.status == TransactionStatus.PENDING,
            Transaction.tx_type == TransactionType.BUY,
            Transaction.trade_date <= today
        ).all()
        
        for tx in pending_txs:
            nav_record = fetch_fund_nav_for_date(tx.fund_code, tx.trade_date, db)
            if nav_record and nav_record.unit_nav and nav_record.nav_date >= tx.trade_date:
                fee_rate = Decimal("0.15")
                if tx.memo and "费率" in tx.memo:
                    import re
                    match = re.search(r'费率([\d.]+)%', tx.memo)
                    if match:
                        fee_rate = Decimal(match.group(1))
                
                net_amount = (tx.amount / (1 + fee_rate / 100)).quantize(Decimal("0.01"))
                fee_amount = tx.amount - net_amount
                shares = (net_amount / nav_record.unit_nav).quantize(Decimal("0.0001"))
                
                holding = db.query(Holding).filter_by(account_id=tx.account_id, fund_code=tx.fund_code).first()
                if not holding:
                    holding = Holding(
                        account_id=tx.account_id,
                        fund_code=tx.fund_code,
                        fund_name=tx.fund_name,
                        shares=Decimal("0"),
                        avg_cost_price=Decimal("0"),
                        total_cost=Decimal("0"),
                    )
                    db.add(holding)
                    db.flush()
                
                new_cost = holding.total_cost + tx.amount
                new_shares = holding.shares + shares
                holding.total_cost = new_cost
                holding.shares = new_shares
                if new_shares > 0:
                    holding.avg_cost_price = (new_cost / new_shares).quantize(Decimal("0.0001"))
                
                tx.status = TransactionStatus.CONFIRMED
                tx.holding_id = holding.id
                tx.shares = shares
                tx.nav_price = nav_record.unit_nav
                tx.fee = fee_amount
                tx.net_amount = net_amount
                tx.confirm_date = nav_record.nav_date
                
                logger.info("盲买交割完成: fund={} date={} shares={}", tx.fund_code, tx.trade_date, shares)
        db.commit()

        # ── Step 1: 拉取所有活跃持仓的最新净值 ─────────────────
        holdings: list[Holding] = (
            db.query(Holding).filter(Holding.shares > 0).all()
        )
        logger.info("当前活跃持仓数量：{}", len(holdings))

        for holding in holdings:
            nav_record = fetch_fund_nav(holding.fund_code, db, force_refresh)
            if nav_record:
                holding.latest_nav_date = nav_record.nav_date
                update_holding_market_value(holding, nav_record.unit_nav, db)

        # ── Step 1.5: 更新本地 CSV 缓存文件（用于回测页面）───────────────────
        _update_csv_cache_files(holdings, db)

        # ── Step 2: 汇总组合数据 ──────────────────────────────────
        db.expire_all()
        holdings = db.query(Holding).filter(Holding.shares > 0).all()

        # ── Step 2.25: 阶梯止盈检查 ─────────────────────────────
        ladder_result = check_ladder_triggers(holdings)
        ladder_triggers = ladder_result["triggers"]
        ladder_statuses = ladder_result["statuses"]

        # ── Step 2.5: 补齐缺失的历史快照 ────────────────────────────
        last_snap = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date < today).order_by(DailySnapshot.snapshot_date.desc()).first()
        if last_snap:
            missing_days = (today - last_snap.snapshot_date).days - 1
            if missing_days > 0:
                logger.info("发现 {} 天缺失快照，开始补齐...", missing_days)
                prev_snap = last_snap
                for i in range(1, missing_days + 1):
                    missing_date = last_snap.snapshot_date + timedelta(days=i)
                    prev_snap = _backfill_snapshot_for_date(missing_date, holdings, prev_snap, db)

        total_cost          = sum(h.total_cost or Decimal("0") for h in holdings)
        total_market_value  = sum(h.market_value or Decimal("0") for h in holdings)
        total_unrealized    = sum(h.unrealized_pnl or Decimal("0") for h in holdings)
        total_pnl_pct = (
            (total_unrealized / total_cost * 100).quantize(Decimal("0.0001"))
            if total_cost else Decimal("0")
        )

        # ── Step 3: 写入每日快照（Upsert：当天已有则更新，否则新建）──────
        holdings_snapshot = json.dumps(
            [
                {
                    "fund_code":          h.fund_code,
                    "fund_name":          h.fund_name,
                    "shares":             str(h.shares),
                    "market_value":       str(h.market_value),
                    "unrealized_pnl":     str(h.unrealized_pnl),
                    "unrealized_pnl_pct": str(h.unrealized_pnl_pct),
                    "current_drawdown":   str(h.current_drawdown),
                }
                for h in holdings
            ],
            ensure_ascii=False,
        )

        snapshot = db.query(DailySnapshot).filter_by(snapshot_date=today).first()
        if snapshot:
            snapshot.total_cost           = total_cost
            snapshot.total_market_value   = total_market_value
            snapshot.total_unrealized_pnl = total_unrealized
            snapshot.total_pnl            = total_unrealized
            snapshot.total_pnl_pct        = total_pnl_pct
            snapshot.holdings_snapshot    = holdings_snapshot
        else:
            snapshot = DailySnapshot(
                snapshot_date=today,
                total_cost=total_cost,
                total_market_value=total_market_value,
                total_unrealized_pnl=total_unrealized,
                total_realized_pnl=Decimal("0"),
                total_pnl=total_unrealized,
                total_pnl_pct=total_pnl_pct,
                holdings_snapshot=holdings_snapshot,
                report_sent=False,
            )
            db.add(snapshot)
        db.commit()
        logger.info("每日快照写入完成，总市值={}", total_market_value)

        # ── Step 4: 生成推送报告 ──────────────────────────────────
        from app.models import NavHistory
        daily_pnl = Decimal("0")
        daily_pnl_by_fund: dict[str, Decimal] = {}
        for h in holdings:
            navs = db.query(NavHistory).filter(NavHistory.fund_code == h.fund_code, NavHistory.nav_date <= today).order_by(NavHistory.nav_date.desc()).limit(2).all()
            if len(navs) == 2:
                curr_nav = navs[0].unit_nav
                prev_nav = navs[1].unit_nav
                fund_daily_pnl = (curr_nav - prev_nav) * h.shares
                daily_pnl += fund_daily_pnl
                daily_pnl_by_fund[h.fund_code] = fund_daily_pnl

        report = _build_report(today, holdings, total_market_value, total_unrealized, total_pnl_pct, daily_pnl, daily_pnl_by_fund, ladder_triggers, ladder_statuses)
        logger.info("推送报告生成完成")

        # 依次尝试邮件、企业微信、PushPlus，若失败则降级重试
        from app.config import settings
        title = f"📊 基金日报 {today.strftime('%Y-%m-%d')}"
        success = False
        
        if settings.SMTP_SERVER and settings.SMTP_USER:
            success = send_email(title=title, content=report)
            
        if not success and settings.WECOM_WEBHOOK_URL:
            # 企业微信只支持 markdown 内容本身，把标题加进去
            full_content = f"# {title}\n\n{report}"
            success = send_wecom(content=full_content)
            
        if not success and settings.PUSHPLUS_TOKEN:
            success = send_wechat(title=title, content=report)

        # 更新推送状态
        snapshot.report_sent = success
        snapshot.report_content = report
        db.commit()

    except Exception as exc:
        db.rollback()
        logger.exception("ETL 主流程异常：{}", exc)
    finally:
        db.close()
        logger.info("========== 每日 ETL 结束 ==========")


def _backfill_snapshot_for_date(target_date: date, current_holdings: list[Holding], prev_snapshot: DailySnapshot, db: Session) -> DailySnapshot | None:
    """自动回填缺失日期的快照。
    
    策略：
    - 如果某基金在 target_date 有净值，用真实净值计算。
    - 如果没有（如节假日/HK基金无数据），沿用 prev_snapshot 里该基金的 market_value 和 pnl，
      避免用错误的历史净值估算导致盈亏跳变。
    """
    # 解析前一天快照，建立 fund_code -> item 的 map
    prev_holdings_map = {}
    if prev_snapshot and prev_snapshot.holdings_snapshot:
        try:
            for item in json.loads(prev_snapshot.holdings_snapshot):
                prev_holdings_map[item["fund_code"]] = item
        except Exception:
            pass

    total_cost = Decimal("0")
    total_market_value = Decimal("0")
    total_unrealized = Decimal("0")
    snap_holdings = []
    
    for h in current_holdings:
        from app.models import NavHistory
        # 优先从本地 nav_history 查找，避免网络失败导致数据丢失
        local_nav = db.query(NavHistory).filter_by(
            fund_code=h.fund_code, nav_date=target_date
        ).first()
        if not local_nav:
            # 本地没有，才尝试网络拉取
            local_nav = fetch_fund_nav_for_date(h.fund_code, target_date, db)
        nav_record = local_nav
        if nav_record and nav_record.unit_nav:
            # 有当日净值：正常计算
            nav = nav_record.unit_nav
            mv = (h.shares * nav).quantize(Decimal("0.01"))
            pnl = mv - h.total_cost
            pnl_pct = (pnl / h.total_cost * 100).quantize(Decimal("0.0001")) if h.total_cost else Decimal("0")
        elif h.fund_code in prev_holdings_map:
            # 无当日净值：沿用前一天快照数据（不做估算，避免引入噪音）
            prev_item = prev_holdings_map[h.fund_code]
            mv = Decimal(str(prev_item["market_value"]))
            pnl = Decimal(str(prev_item["unrealized_pnl"]))
            pnl_pct = Decimal(str(prev_item.get("unrealized_pnl_pct", "0")))
            logger.debug("基金 {} 在 {} 无净值，水平延用前一天快照数据", h.fund_code, target_date)
        else:
            # fallback
            mv = h.market_value or Decimal("0")
            pnl = h.unrealized_pnl or Decimal("0")
            pnl_pct = h.unrealized_pnl_pct or Decimal("0")
        
        total_cost += h.total_cost
        total_market_value += mv
        total_unrealized += pnl
        
        snap_holdings.append({
            "fund_code": h.fund_code,
            "fund_name": h.fund_name,
            "shares": str(h.shares),
            "market_value": str(mv),
            "unrealized_pnl": str(pnl),
            "unrealized_pnl_pct": str(pnl_pct),
            "current_drawdown": str(h.current_drawdown or 0),
        })
        
    total_pnl_pct = (total_unrealized / total_cost * 100).quantize(Decimal("0.0001")) if total_cost else Decimal("0")
    
    snapshot = DailySnapshot(
        snapshot_date=target_date,
        total_cost=total_cost,
        total_market_value=total_market_value,
        total_unrealized_pnl=total_unrealized,
        total_realized_pnl=Decimal("0"),
        total_pnl=total_unrealized,
        total_pnl_pct=total_pnl_pct,
        holdings_snapshot=json.dumps(snap_holdings, ensure_ascii=False),
        report_sent=False,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    logger.info("补齐快照写入完成: date={} 总市值={}", target_date, total_market_value)
    return snapshot


def _build_report(
    today: date,
    holdings: list[Holding],
    total_mv: Decimal,
    total_pnl: Decimal,
    total_pnl_pct: Decimal,
    daily_pnl: Decimal = Decimal("0"),
    daily_pnl_by_fund: dict[str, Decimal] | None = None,
    ladder_triggers: list[dict] | None = None,
    ladder_statuses: list[dict] | None = None,
) -> str:
    """构建 Markdown 格式的日报正文"""
    pnl_color = "#FF0000" if total_pnl >= 0 else "#008000"
    daily_pnl_color = "#FF0000" if daily_pnl > 0 else "#008000"
    
    lines = [
        f"## {today.strftime('%Y年%m月%d日')} 基金日报",
        "",
        "### 账户总览",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总市值 | **¥{total_mv:,.2f}** |",
        f"| 浮动盈亏 | <font color='{pnl_color}'>{'+' if total_pnl >= 0 else ''}¥{total_pnl:,.2f} ({total_pnl_pct:.2f}%)</font> |",
        f"| 今日盈亏 | <font color='{daily_pnl_color}'>{'+' if daily_pnl >= 0 else ''}¥{daily_pnl:,.2f}</font> |",
        "",

        "### 持仓明细",
        "| 基金 | 市值 | 盈亏率 | 今日盈亏 | 净值日期 | 当前回撤 |",
        "|------|------|--------|----------|----------|----------|",
    ]

    for h in sorted(holdings, key=lambda x: x.market_value or 0, reverse=True):
        pnl_val = float(h.unrealized_pnl_pct or 0)
        pnl_color = "#FF0000" if pnl_val >= 0 else "#008000"
        pnl_str = f"<font color='{pnl_color}'>{pnl_val:.2f}%</font>" if h.unrealized_pnl_pct else "N/A"
        
        dd_val = float(h.current_drawdown or 0)
        if dd_val <= -15:
            dd_str = f"<font color='#8B008B'><strong>{dd_val:.2f}%</strong></font>"
        elif dd_val <= -10:
            dd_str = f"<font color='#DC143C'><strong>{dd_val:.2f}%</strong></font>"
        elif dd_val <= -5:
            dd_str = f"<font color='#FF8C00'>{dd_val:.2f}%</font>"
        else:
            dd_str = f"<font color='#808080'>{dd_val:.2f}%</font>"
        
        mv_str = f"¥{h.market_value:,.2f}" if h.market_value else "N/A"
        date_str = h.latest_nav_date.strftime("%m-%d") if h.latest_nav_date else "N/A"
        
        if daily_pnl_by_fund and h.fund_code in daily_pnl_by_fund:
            daily_pnl_val = daily_pnl_by_fund[h.fund_code]
            daily_pnl_color = "#FF0000" if daily_pnl_val >= 0 else "#008000"
            daily_pnl_str = f"<font color='{daily_pnl_color}'>{'+' if daily_pnl_val >= 0 else ''}¥{daily_pnl_val:,.2f}</font>"
        else:
            daily_pnl_str = "N/A"
            
        lines.append(
            f"| {h.fund_name}({h.fund_code}) | {mv_str} | {pnl_str} | {daily_pnl_str} | {date_str} | {dd_str} |"
        )

    # ── 定投提醒（仅定投日显示）──────────────────────────────────
    dca_weekday = today.weekday()
    is_dca_day = any(
        h.dca_enabled and h.dca_day_of_week == dca_weekday and h.dca_weekly_amount
        for h in holdings
    )

    if is_dca_day:
        alerts = []
        action_guides = []

        for h in holdings:
            if h.dca_enabled and h.dynamic_dca_enabled and h.dca_weekly_amount and h.dca_day_of_week == dca_weekday:
                base = float(h.dca_weekly_amount)
                # 支付宝口径：用 T-1 净值计算盈亏率
                t1_nav = db.query(NavHistory).filter(
                    NavHistory.fund_code == h.fund_code
                ).order_by(NavHistory.nav_date.desc()).offset(1).limit(1).first()
                if t1_nav and h.avg_cost_price and float(h.avg_cost_price) > 0:
                    pnl_pct = (float(t1_nav.unit_nav) - float(h.avg_cost_price)) / float(h.avg_cost_price) * 100
                else:
                    pnl_pct = float(h.unrealized_pnl_pct or 0)
                rate = get_dca_deduction_rate(pnl_pct)
                actual = base * rate
                weekly_amount = round(actual, 2)

                if rate >= 1.5:
                    alerts.append(f"<font color='#008000'>**[今日定投 - 加倍]**</font> {h.fund_name}：扣款 ¥{weekly_amount:.0f}（基础¥{base:.0f}×扣款率{rate:.2f}），当前亏损{pnl_pct:+.2f}%。")
                elif rate <= 0.6:
                    action_guides.append(f"<font color='#FF8C00'>**[今日定投 - 减半]**</font> {h.fund_name}：扣款 ¥{weekly_amount:.0f}（基础¥{base:.0f}×扣款率{rate:.2f}），当前盈利{pnl_pct:+.2f}%。")
                elif pnl_pct <= -5:
                    action_guides.append(f"<font color='#FF8C00'>**[今日定投 - 加速]**</font> {h.fund_name}：扣款 ¥{weekly_amount:.0f}（基础¥{base:.0f}×扣款率{rate:.2f}），当前亏损{pnl_pct:+.2f}%。")
                else:
                    action_guides.append(f"**[今日定投]** {h.fund_name}：扣款 ¥{weekly_amount:.0f}（基础¥{base:.0f}×扣款率{rate:.2f}），当前盈亏{pnl_pct:+.2f}%。")

        if alerts:
            lines.append("")
            lines.append("### 今日定投")
            for alert in alerts:
                lines.append(alert)
                lines.append("")

        if action_guides:
            if not alerts:
                lines.append("")
                lines.append("### 今日定投")
            for guide in action_guides:
                lines.append(guide)
                lines.append("")

    # ── 阶梯止盈状态 ────────────────────────────────────────────
    if ladder_statuses:
        lines.append("")
        lines.append("### 阶梯止盈监控")
        lines.append("")
        for s in ladder_statuses:
            triggered_count = len(s["triggered"])
            total_count = len(LADDER_LEVELS)

            # 构建已触发档位描述
            triggered_descs = []
            for i in s["triggered"]:
                th = int(LADDER_LEVELS[i][0] * 100)
                sr = int(LADDER_LEVELS[i][1] * 100)
                triggered_descs.append(f"+{th}%卖{sr}%")

            # 下一档信息
            if s["next_level"] < len(LADDER_LEVELS):
                next_th = int(LADDER_LEVELS[s['next_level']][0] * 100)
                next_sr = int(LADDER_LEVELS[s['next_level']][1] * 100)
                target_nav = s.get('target_nav', 0)
                gap = s.get('gap_pct', 0)
                next_desc = f"下一档 **+{next_th}%卖{next_sr}%**，需净值 ≥ ¥{target_nav:.4f}（还差 {gap:+.1f}%）"
            else:
                next_desc = "已全部触发，待浮盈回落至 5% 以下自动重置"

            if triggered_count > 0:
                trigger_str = "、".join(triggered_descs)
                name_line = (
                    f"<font color='#FF0000'>**[{triggered_count}/{total_count} 已触发]**</font> "
                    f"**{s['name']}**（{s['code']}）：浮盈 {s['pp']:+.1f}%"
                )
                lines.append(name_line)
                lines.append(f"  已触发：<font color='#FF0000'>{trigger_str}</font>")
                lines.append(f"  {next_desc}")
            else:
                name_line = (
                    f"**{s['name']}**（{s['code']}）：浮盈 {s['pp']:+.1f}%，尚未触发任何档位"
                )
                lines.append(name_line)
                lines.append(f"  {next_desc}")

            lines.append("")

    if ladder_triggers:
        lines.append("")
        lines.append("### 阶梯止盈触发 - 建议操作")
        for t in ladder_triggers:
            lines.append(
                f"- <font color='#FF0000'>**[卖出]**</font> {t['name']}({t['code']}): "
                f"触发 {', '.join(f'+{l}%' for l in t['new_levels'])}档, "
                f"建议卖出 **¥{t['sell_amount']:,.2f}** (约 {t['sell_shares']:.2f} 份) "
                f"@ NAV ¥{t['nav']:.4f}"
            )

    lines += [
        "",
        "---",
        f"*数据更新时间：{datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')} CST*",
    ]
    return "\n".join(lines)


def _update_csv_cache_files(holdings: list[Holding], db: Session) -> None:
    """更新本地 CSV 缓存文件（用于回测页面）"""
    import os
    import pandas as pd
    from pathlib import Path
    from app.models import NavHistory
    
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    for holding in holdings:
        cache_file = data_dir / f"{holding.fund_code}_history_v2.csv"
        
        navs = (
            db.query(NavHistory)
            .filter(NavHistory.fund_code == holding.fund_code)
            .order_by(NavHistory.nav_date.asc())
            .all()
        )
        
        if not navs:
            continue
            
        df = pd.DataFrame([
            {
                "净值日期": str(n.nav_date),
                "单位净值": float(n.unit_nav or 0),
                "累计净值": float(n.accum_nav or n.unit_nav or 0),
            }
            for n in navs
        ])
        
        df.to_csv(cache_file, index=False)
        logger.info("CSV 缓存已更新: {}", cache_file.name)
