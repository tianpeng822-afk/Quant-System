import akshare as ak
import pandas as pd

# Indices to check:
# 000300 沪深300
# 399006 创业板指
# 000932 中证消费
# 000938 中证医药
# 399997 中证白酒
# 399986 中证银行
# 000905 中证500
# 931186 科技龙头

indices = {
    "沪深300": "000300.XSHG",
    "创业板指": "399006.XSHE",
    "中证500": "000905.XSHG",
}

print("fetching index PE...")
try:
    for name, code in indices.items():
        symbol = name # Akshare lg often uses index names like 沪深300
        try:
            df = ak.stock_index_pe_lg(symbol=symbol)
            if not df.empty:
                pe_col = [c for c in df.columns if '市盈率' in c][-1]
                latest_pe = float(df[pe_col].iloc[-1])
                pe_series = df[pe_col].dropna()
                percentile = (pe_series < latest_pe).sum() / len(pe_series) * 100
                print(f"{name}: PE={latest_pe:.2f}, 分位点={percentile:.2f}%")
        except Exception as e:
            print(f"Failed for {name}: {e}")
except Exception as e:
    print(f"Error: {e}")

