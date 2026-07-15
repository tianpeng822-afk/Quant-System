import pandas as pd

df_A = pd.read_csv('data/003376_history_v2.csv')
df_B = pd.read_csv('data/000051_history_v2.csv')
df_A['净值日期'] = pd.to_datetime(df_A['净值日期'])
df_B['净值日期'] = pd.to_datetime(df_B['净值日期'])

# Get start NAV in 2017
start_A = df_A[df_A['净值日期'] >= '2017-01-01'].iloc[0]['累计净值']
end_A = df_A.iloc[-1]['累计净值']

start_B = df_B[df_B['净值日期'] >= '2017-01-01'].iloc[0]['累计净值']
end_B = df_B.iloc[-1]['累计净值']

print(f"Fund A (Bond) total return (2017-now): {end_A/start_A - 1:.2%}")
print(f"Fund B (Stock) total return (2017-now): {end_B/start_B - 1:.2%}")
