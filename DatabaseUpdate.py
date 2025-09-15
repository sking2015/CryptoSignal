import sqlite3
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

DB_FILE = "kline.db"


def ts_to_str(ts: int, tz_offset: int = 8) -> str:
    """
    将Unix时间戳(秒)转为可读日期字符串
    默认转换为北京时间 (UTC+8)
    """
    tz = timezone(timedelta(hours=tz_offset))
    dt = datetime.fromtimestamp(ts, tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def init_table(conn,table):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {table} (
        ts INTEGER PRIMARY KEY,   -- 时间戳(秒)
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        amount REAL,
        vol REAL,
        count INTEGER
    )
    """)
    conn.commit()    


def fetch_kline(symbol, period, size):
    url = "https://api.huobi.pro/market/history/kline"
    params = {"symbol": symbol, "period": period, "size": size}
    resp = requests.get(url, params=params).json()
    data = resp.get("data", [])
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df = df.sort_values("id")  # id 是时间戳（秒）
    df = df.rename(columns={"id": "ts"})
    return df[["ts", "open", "high", "low", "close", "amount", "vol", "count"]]


def get_latest_ts(conn,table):
    cursor = conn.cursor()
    cursor.execute(f"SELECT MAX(ts) FROM {table}")
    result = cursor.fetchone()
    return result[0] if result and result[0] else None


def update_kline(conn,symbol,period):
    table = symbol + "_" + period

    print("处理表:",table)

    interval = PERIOD_INTERVAL[period]
    
    last_ts = get_latest_ts(conn,table)

    if last_ts is not None:
        print("本地表最后一条时间:" + ts_to_str(last_ts))
    else:
        print("本地尚无数据")

    # 获取最新一根K线，确认当前市场时间
    latest_df = fetch_kline(symbol, period, 1)
    if latest_df.empty:
        print("❌ API返回空数据")
        return
    latest_ts = int(latest_df.iloc[-1]["ts"])


    print("云端数据最后一条时间:" + ts_to_str(latest_ts))

    if last_ts is None:
        # 数据库为空，拉100根
        print(f"📥{table} 表为空，拉取100根")
        df = fetch_kline(symbol, period, 100)
        if not df.empty:
            df.to_sql(table, conn, if_exists="append", index=False)
    else:
        # 计算缺多少根
        missing = (latest_ts - last_ts) // interval
        if missing <= 0:
            print(f"{table}✅ 已是最新，无需更新")
        else:
            need = min(missing, 100)
            print(f"{table}📥 缺少 {missing} 根，拉取 {need} 根")
            df = fetch_kline(symbol, period, need)
            # 过滤掉数据库里已有的数据
            df = df[df["ts"] > last_ts]
            if not df.empty:
                df.to_sql(table, conn, if_exists="append", index=False)
    

PERIOD_INTERVAL = {
    "5min":300,
    "15min":900,
    "30min":1800,
    "60min":3600,
    "2hour":7200,
    "4hour":14400,
    "6hour":3600*6,
    "12hour":3600*12,
    "1day":3600*24,
    "3day":3600*24*3,
    "1week":3600*24*7
}

def update_all_kline(symbol,conn):
       
    for period in PERIOD_INTERVAL.keys():
        tabel = f"{symbol}_{period}"
        init_table(conn,tabel)
        update_kline(conn,symbol,period)
    

HOT_SYMBOLS = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt",
    "wldusdt","wlfiusdt","kaitousdt","uniusdt"
]

def update_all_symbol():
    conn = sqlite3.connect(DB_FILE) 
    for symbol in HOT_SYMBOLS:
        update_all_kline(symbol,conn)

    conn.close()



if __name__ == "__main__":
    update_all_symbol()    
