import pandas as pd

df_A = pd.read_csv('data/003376_history_v2.csv')
df_B = pd.read_csv('data/000051_history_v2.csv')

df_A['nav_max'] = df_A['累计净值'].cummax()
df_A['dd'] = (df_A['累计净值'] - df_A['nav_max']) / df_A['nav_max']

df_B['nav_max'] = df_B['累计净值'].cummax()
df_B['dd'] = (df_B['累计净值'] - df_B['nav_max']) / df_B['nav_max']

print(f"Fund A (003376) Max DD: {df_A['dd'].min()*100:.2f}%")
print(f"Fund B (000051) Max DD: {df_B['dd'].min()*100:.2f}%")

df_merged = pd.merge(df_A, df_B, on='净值日期', how='inner').sort_values('净值日期').ffill().dropna()

recent = df_merged[df_merged['净值日期'] >= '2021-01-01']
print(f"In 2021-2024, Fund A (003376) return: {recent['累计净值_x'].iloc[-1]/recent['累计净值_x'].iloc[0] - 1:.2%}")
print(f"In 2021-2024, Fund B (000051) return: {recent['累计净值_y'].iloc[-1]/recent['累计净值_y'].iloc[0] - 1:.2%}")
