"""
净值抓取器（Phase 1 骨架）
────────────────────────────────────────────────
使用 AkShare 拉取指定基金代码的当日最新净值，
写入 nav_history 表，并刷新 holdings 表的市值字段。
"""

from datetime import date
from decimal import Decimal

import akshare as ak
import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

from app.models import NavHistory, Holding

import functools
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_fixed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def _fetch_akshare_nav(symbol: str):
    return ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")

@functools.lru_cache(maxsize=1)
def get_hk_fund_map():
    try:
        df = ak.fund_hk_rank_em()
        return dict(zip(df["基金代码"], df["香港基金代码"]))
    except Exception as e:
        logger.error(f"Error fetching HK rank: {e}")
        return {}

def fetch_hk_fund_nav(fund_code: str, target_date: date | None = None) -> NavHistory | None:
    hk_map = get_hk_fund_map()
    hkfcode = hk_map.get(fund_code)
    if not hkfcode:
        return None
    
    url = f"https://overseas.1234567.com.cn/overseasapi/OpenApiHander.ashx?api=HKFDApi&m=MethodJZ&hkfcode={hkfcode}&action=2&pageindex=0&pagesize=100&date1=&date2="
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        data = resp.json()
        if data.get("Code") == "1" and data.get("Data"):
            items = data["Data"]
            if target_date:
                target_str = target_date.strftime("%Y-%m-%d")
                for item in items:
                    if item.get("PDATE") == target_str:
                        return NavHistory(
                            fund_code=fund_code,
                            fund_name="",
                            nav_date=target_date,
                            unit_nav=Decimal(str(item.get("NAV", 0))),
                            source="HK_API"
                        )
                return None
            else:
                item = items[0]
                return NavHistory(
                    fund_code=fund_code,
                    fund_name="",
                    nav_date=datetime.strptime(item.get("PDATE"), "%Y-%m-%d").date(),
                    unit_nav=Decimal(str(item.get("NAV", 0))),
                    source="HK_API"
                )
    except Exception as e:
        logger.error(f"Error fetching HK NAV for {fund_code}: {e}")
    return None


def _get_expected_nav_date() -> date:
    """计算应该期望的最新净值日期"""
    today = date.today()
    now = datetime.now()
    
    if today.weekday() >= 5:
        if today.weekday() == 5:
            return today - timedelta(days=1)
        else:
            return today - timedelta(days=2)
    else:
        if now.hour >= 15:
            return today
        else:
            return today - timedelta(days=1)


def fetch_fund_nav(fund_code: str, db: Session, force_refresh: bool = False) -> NavHistory | None:
    """
    从 AkShare 拉取单只基金最新净值并存入 nav_history。
    缓存优先策略：如果数据库中已有最新日期的净值，直接返回缓存。

    Parameters
    ----------
    fund_code     : 基金代码，如 "110022"
    db            : SQLAlchemy Session
    force_refresh : 是否强制刷新，True 时跳过缓存直接拉取

    Returns
    -------
    NavHistory 实例（已 commit），或 None（若拉取失败）
    """
    expected_date = _get_expected_nav_date()
    
    cached = (
        db.query(NavHistory)
        .filter(NavHistory.fund_code == fund_code)
        .order_by(NavHistory.nav_date.desc())
        .first()
    )
    
    if not force_refresh and cached and cached.nav_date >= expected_date:
        logger.debug("缓存命中，直接返回。fund={} date={}", fund_code, cached.nav_date)
        return cached
    
    logger.info("开始拉取净值。fund={} expected_date={} cached_date={} force={}", fund_code, expected_date, cached.nav_date if cached else None, force_refresh)
    
    try:
        df = _fetch_akshare_nav(symbol=fund_code)
        if df is None or df.empty:
            logger.warning("AkShare 返回空数据，fund_code={}", fund_code)
            return cached if cached else None

        latest = df.iloc[-1]
        date_col = "净值日期" if "净值日期" in df.columns else df.columns[0]
        nav_col  = "单位净值" if "单位净值" in df.columns else df.columns[1]
        acc_col  = "累计净值" if "累计净值" in df.columns else None
        ret_col  = "日增长率" if "日增长率" in df.columns else None

        nav_date: date = latest[date_col].date() if hasattr(latest[date_col], 'date') else latest[date_col]
        unit_nav = Decimal(str(latest[nav_col]))
        accum_nav = Decimal(str(latest[acc_col])) if acc_col else None
        daily_return = (
            Decimal(str(latest[ret_col])) if ret_col else None
        )

        existing = (
            db.query(NavHistory)
            .filter_by(fund_code=fund_code, nav_date=nav_date)
            .first()
        )
        if existing:
            if existing.unit_nav == unit_nav:
                logger.debug("净值已存在且未变化。fund={} date={}", fund_code, nav_date)
                return existing
            else:
                logger.info("净值已更新，覆盖旧数据。fund={} date={} old={} new={}", fund_code, nav_date, existing.unit_nav, unit_nav)
                existing.unit_nav = unit_nav
                existing.accum_nav = accum_nav
                existing.daily_return = daily_return
                existing.source = "AkShare"
                db.commit()
                db.refresh(existing)
                return existing

        nav_record = NavHistory(
            fund_code=fund_code,
            fund_name=str(df.attrs.get("name", "")),
            nav_date=nav_date,
            unit_nav=unit_nav,
            accum_nav=accum_nav,
            daily_return=daily_return,
            source="AkShare",
        )
        db.add(nav_record)
        db.commit()
        db.refresh(nav_record)
        logger.info("净值已写入 fund={} date={} nav={}", fund_code, nav_date, unit_nav)
        return nav_record

    except Exception as exc:
        db.rollback()
        logger.warning(f"Normal API failed for {fund_code}, trying HK API: {exc}")
        hk_nav = fetch_hk_fund_nav(fund_code)
        if hk_nav:
            existing = db.query(NavHistory).filter_by(
                fund_code=fund_code, nav_date=hk_nav.nav_date
            ).first()
            if existing:
                if existing.unit_nav == hk_nav.unit_nav:
                    logger.debug("HK API 净值已存在且未变化。fund={} date={}", fund_code, hk_nav.nav_date)
                    return existing
                else:
                    logger.info("HK API 净值已更新，覆盖旧数据。fund={} date={} old={} new={}", fund_code, hk_nav.nav_date, existing.unit_nav, hk_nav.unit_nav)
                    existing.unit_nav = hk_nav.unit_nav
                    existing.source = "HK_API"
                    db.commit()
                    db.refresh(existing)
                    return existing
            hk_nav.source = "HK_API"
            db.add(hk_nav)
            db.commit()
            return hk_nav
        return cached if cached else None


def fetch_fund_nav_for_date(fund_code: str, target_date: date, db: Session) -> NavHistory | None:
    """
    从 AkShare 获取单只基金指定日期的净值并存入 nav_history。
    如果指定日期无数据（如节假日，或当天还没出净值），则返回 None。
    """
    try:
        df = _fetch_akshare_nav(symbol=fund_code)
        if df is None or df.empty:
            return None

        # 兼容不同版本的列名
        date_col = "净值日期" if "净值日期" in df.columns else df.columns[0]
        nav_col  = "单位净值" if "单位净值" in df.columns else df.columns[1]
        acc_col  = "累计净值" if "累计净值" in df.columns else None
        ret_col  = "日增长率" if "日增长率" in df.columns else None

        # 提取目标日期的行
        # 将 date_col 转为 python date 对象进行比对
        df['__date'] = pd.to_datetime(df[date_col]).dt.date
        target_row = df[df['__date'] == target_date]
        
        if target_row.empty:
            logger.debug("未找到指定日期的净值，fund={} date={}", fund_code, target_date)
            return None
            
        row = target_row.iloc[0]
        
        unit_nav = Decimal(str(row[nav_col]))
        accum_nav = Decimal(str(row[acc_col])) if acc_col and pd.notna(row[acc_col]) else None
        daily_return = Decimal(str(row[ret_col])) if ret_col and pd.notna(row[ret_col]) else None

        # 检查是否已存在
        existing = db.query(NavHistory).filter_by(fund_code=fund_code, nav_date=target_date).first()
        if existing:
            return existing

        nav_record = NavHistory(
            fund_code=fund_code,
            fund_name=str(df.attrs.get("name", "")),
            nav_date=target_date,
            unit_nav=unit_nav,
            accum_nav=accum_nav,
            daily_return=daily_return,
            source="AkShare",
        )
        db.add(nav_record)
        db.commit()
        db.refresh(nav_record)
        return nav_record

    except Exception as exc:
        db.rollback()
        logger.warning(f"Normal API failed for {fund_code}, trying HK API for historical NAV: {exc}")
        
        # search backwards 14 days
        for i in range(15):
            past_date = target_date - timedelta(days=i)
            hk_nav = fetch_hk_fund_nav(fund_code, past_date)
            if hk_nav:
                existing = db.query(NavHistory).filter_by(
                    fund_code=fund_code, nav_date=hk_nav.nav_date
                ).first()
                if existing:
                    return existing
                hk_nav.source = "HK_API"
                db.add(hk_nav)
                db.commit()
                db.refresh(hk_nav)
                return hk_nav
        return None

def update_holding_market_value(holding: Holding, nav: Decimal, db: Session) -> None:
    """
    用最新净值刷新单条 Holding 的市值、浮动盈亏、回撤等字段。

    Parameters
    ----------
    holding : 目标持仓记录
    nav     : 当日单位净值
    db      : SQLAlchemy Session
    """
    holding.latest_nav = nav
    holding.market_value = (holding.shares * nav).quantize(Decimal("0.01"))
    holding.unrealized_pnl = holding.market_value - holding.total_cost
    if holding.total_cost and holding.total_cost != 0:
        holding.unrealized_pnl_pct = (
            holding.unrealized_pnl / holding.total_cost * 100
        ).quantize(Decimal("0.0001"))

    # 更新历史最高净值（用于回撤计算）
    if holding.peak_nav is None or nav > holding.peak_nav:
        holding.peak_nav = nav

    if holding.peak_nav and holding.peak_nav != 0:
        holding.current_drawdown = (
            (nav - holding.peak_nav) / holding.peak_nav * 100
        ).quantize(Decimal("0.0001"))

    # 更新历史最高浮盈率（用于移动止盈）
    if holding.unrealized_pnl_pct is not None:
        if holding.peak_pnl_pct is None or holding.unrealized_pnl_pct > holding.peak_pnl_pct:
            holding.peak_pnl_pct = holding.unrealized_pnl_pct

    db.add(holding)
    db.commit()
    logger.debug(
        "Holding 刷新完成 fund={} mv={} pnl={} drawdown={}",
        holding.fund_code,
        holding.market_value,
        holding.unrealized_pnl_pct,
        holding.current_drawdown,
    )
