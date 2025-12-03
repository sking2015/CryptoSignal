import sqlite3
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from ConstDef import g_ACD


def ts_to_str(ts: int, tz_offset: int = 8) -> str:
    """
    将Unix时间戳(秒)转为可读日期字符串
    默认转换为北京时间 (UTC+8)
    """

    print("ts",ts,"tz_offset",tz_offset)
    tz = timezone(timedelta(hours=tz_offset))
    dt = datetime.fromtimestamp(ts, tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def init_table(conn,table):
    # conn = sqlite3.connect(DB_FILE)
    # print("尝试建表",table)
    cursor = conn.cursor()
    if g_ACD.getExchange() == "HTX":
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
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
    else:
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
            open_time INTEGER PRIMARY KEY,   -- 时间戳(秒)
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            close_time INTEGER,
            quote_asset_volume REAL,
            num_trades INTEGER,
            taker_base_vol REAL,
            taker_quote_vol REAL
        )
        """)        
    conn.commit()       


def fetch_kline_by_HTX(symbol, period, size):
    url = g_ACD.getApiKline()
    params = {"symbol": symbol, "period": period, "size": size}

    resp = requests.get(url, params=params).json()    
    print("拉取结果",resp)
    data = resp.get("data", [])
    

    df = pd.DataFrame(data)
    if df.empty:
        return df      


    df = df.sort_values("id")  # id 是时间戳（秒）
    df = df.rename(columns={"id": "ts"})
    df = df.drop_duplicates(subset=["ts"])
    return df[["ts", "open", "high", "low", "close", "amount", "vol", "count"]]

def fetch_kline_by_binance(symbol, period, size):
    url = g_ACD.getApiKline()
    params = {"symbol": symbol, "interval": period, "limit": size}
    # print("拉取",url)
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"{symbol} 请求失败: {e}")
        return pd.DataFrame()
    
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_base_vol","taker_quote_vol","ignore"
    ])  
    df = df.drop(columns=["ignore"])
    df = df.drop_duplicates(subset=["open_time"])  
    return df

def fetch_kline(symbol, period, size):
    

    if g_ACD.getExchange() == "HTX":
        return fetch_kline_by_HTX(symbol, period, size)
    else:
        return fetch_kline_by_binance(symbol, period, size)


def get_latest_ts(conn,table):
    cursor = conn.cursor()
    indexname = g_ACD.getIndexName()
    cursor.execute(f'SELECT MAX({indexname}) FROM "{table}"')
    result = cursor.fetchone()
    lastts = None    
    if result and result[0]:
        if g_ACD.getExchange() == "BINANCE":        
            lastts = result[0]/1000
            print("看一下返回的lastts",lastts)
        else:
            lastts = result[0]

    return lastts


def update_kline(conn,symbol,period):
    table = symbol + "_" + period

    print("处理表:",table)

    dictInterval = g_ACD.getInterval()

    interval = dictInterval[period]
    
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
    
    indexname = g_ACD.getIndexName()
    latest_ts = int(latest_df.iloc[-1][indexname])
    if g_ACD.getExchange() == "BINANCE":
        latest_ts /= 1000        


    print("云端数据最后一条时间:" + ts_to_str(latest_ts))

    if last_ts is None:
        # 数据库为空，拉100根
        print(f"📥{table} 表为空，拉取300根")
        df = fetch_kline(symbol, period, 300)
        if not df.empty:             
            df.to_sql(table, conn, if_exists="append", index=False)
    else:
        # 计算缺多少根
        missing = (latest_ts - last_ts) // interval
        if missing <= 0:
            print(f"{table}✅ 已是最新，无需更新")
        else:
            need = int(min(missing, 300))
            print(f"{table}📥 缺少 {missing} 根，拉取 {need} 根")
            df = fetch_kline(symbol, period, need)
            # 过滤掉数据库里已有的数据
            print("当前df",df)
            if df is None or len(df) == 0:
                print(f"未能取得{table}数据,跳过~!")
                return
            
            df = df[df[indexname] > last_ts]
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

    dictInterval = g_ACD.getInterval()
       
    for period in dictInterval.keys():
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
    conn = sqlite3.connect(g_ACD.getDB()) 
    for symbol in HOT_SYMBOLS:
        update_all_kline(symbol,conn)

    conn.close()

def get_all_symbols_from_net(conn):
    url = "https://api.huobi.pro/v1/common/symbols"
    resp = requests.get(url)
    data = resp.json()
    if data["status"] == "ok":
        symbols = [item["symbol"] for item in data["data"]]
        symbolsdata = data["data"]
        # print("拉取结果",symbolsdata)

        df = pd.DataFrame(symbolsdata) 
        df = df[["symbol", "symbol-partition", "state", "api-trading"]]
        print("所有数据",df)
        
        if not df.empty:                        
            df.to_sql(SYMBOLS_TALBE, conn, if_exists="replace", index=True)    
            print(f"已向数据库写入{len(df)}条数据")

        return symbols
    else:
        raise Exception(f"API error: {data}")
    
def get_all_symbols_from_database(conn):
    query = f"SELECT symbol, state {SYMBOLS_TALBE} ORDER BY ts DESC LIMIT {limit+2}"
    df = pd.read_sql(query, conn).sort_values("ts")

if __name__ == "__main__":

    conn = sqlite3.connect(g_ACD.getDB()) 
    symbols = get_all_symbols_from_net(conn)

    conn.close()

    print(f"交易对总数: {len(symbols)}")
    print("前10个交易对:", symbols[:10])
    # update_all_symbol()    


