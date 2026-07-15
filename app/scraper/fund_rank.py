import akshare as ak
from loguru import logger
import pandas as pd

def fetch_top_funds(target_fund_code: str = None, limit: int = 20) -> list[dict]:
    """
    获取开放式基金排行 (基于天天基金)
    新增：根据目标基金的代码，自动寻找同类基金，并计算综合稳定性评分。
    """
    symbol = "全部"
    if target_fund_code:
        try:
            df_names = ak.fund_name_em()
            fund_info = df_names[df_names['基金代码'] == target_fund_code]
            if not fund_info.empty:
                fund_type = fund_info.iloc[0]['基金类型']
                if '混合' in fund_type:
                    symbol = '混合型'
                elif '股票' in fund_type:
                    symbol = '股票型'
                elif '债券' in fund_type:
                    symbol = '债券型'
                elif '指数' in fund_type:
                    symbol = '指数型'
                elif 'QDII' in fund_type:
                    symbol = 'QDII'
                logger.info(f"目标基金 {target_fund_code} 属于 '{fund_type}'，已锁定拉取池为: {symbol}")
        except Exception as e:
            logger.warning(f"获取目标基金类型失败，将使用全市场拉取: {e}")

    logger.info(f"正在拉取 {symbol} 基金排行数据...")
    try:
        df = ak.fund_open_fund_rank_em(symbol=symbol)
        
        # 转换数据类型
        for col in ["近6月", "近1年", "近2年", "近3年"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # 过滤掉连近1年数据都没有的新基金
        df = df.dropna(subset=["近1年"])
        
        # 算法升级：综合稳定性评分 (近1年+近2年+近3年)，偏好长期稳健赢家，而不是单边暴涨的“妖基”
        df["近2年_safe"] = df.get("近2年", df["近1年"]).fillna(df["近1年"])
        df["近3年_safe"] = df.get("近3年", df["近1年"]).fillna(df["近1年"])
        df["综合评分"] = df["近1年"] * 0.4 + df["近2年_safe"] * 0.3 + df["近3年_safe"] * 0.3
        
        # 排除掉自己
        if target_fund_code:
            df = df[df["基金代码"] != target_fund_code]
            
        df = df.sort_values(by="综合评分", ascending=False)
        
        top_df = df.head(limit)
        return top_df.to_dict("records")
    except Exception as e:
        logger.error(f"拉取基金排行失败: {e}")
        return []
