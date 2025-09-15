import asyncio
from htx_get import fetch_signals
import pandas as pd
import sqlite3

periodlist = ["5min,15min,30min,60min,120min,1day,3day"]

hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt",
    "wldusdt","wlfiusdt","kaitousdt","uniusdt"
]

df = fetch_signals("ethusdt", "30min", 100, True)

conn = sqlite3.connect("Cropytdata.db")


df.to_sql("test", conn, if_exists="replace", index=False)

# 4. 从 SQLite 读取刚才存的表
df2 = pd.read_sql("SELECT * FROM test", conn)
print("\n从 SQLite 读出来的 DataFrame:")
print(df2)

# 5. 关闭连接
conn.close()

