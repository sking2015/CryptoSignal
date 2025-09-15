import sqlite3
import requests
import pandas as pd
from DatabaseUpdate import DB_FILE,HOT_SYMBOLS,update_all_symbol

def get_current_price(symbol):
    """
    从HTX获取最新成交价
    """
    url = f"https://api.huobi.pro/market/trade?symbol={symbol}"
    resp = requests.get(url).json()
    return float(resp["tick"]["data"][0]["price"])

# 计算布林带并检测突破
def check_bollinger_breakout(conn, table: str, price,period: int = 20, num_std: float = 2.0):
    """
    从指定K线表取数据，计算布林带，检查最新价格是否触及上/下轨
    :param conn: sqlite3.Connection
    :param table: 表名 (例如 'kline_30min')
    :param period: 布林周期 (默认20)
    :param num_std: 标准差倍数 (默认2)
    """
    # 取最近 period+2 根数据，保证够算
    query = f"SELECT ts, close, high, low FROM {table} ORDER BY ts DESC LIMIT {period+2}"
    df = pd.read_sql(query, conn).sort_values("ts")

    if len(df) < period:
        print(f"⚠️ {table} 数据不足 {period} 根，无法计算布林带")
        return

    # 计算布林带
    df["ma"] = df["close"].rolling(period).mean()
    df["std"] = df["close"].rolling(period).std()
    df["upper"] = df["ma"] + num_std * df["std"]
    df["lower"] = df["ma"] - num_std * df["std"]

    latest = df.iloc[-1]
    # price = latest["close"]
    khprice = latest["high"]
    klprice = latest["low"]
    
    # print("当前布林带数据",df)
    # print("当前价格",price)
    if price >= latest["upper"]:
        print(f"📈 {table} 最新价 {price} 触及布林上轨 {latest['upper']:.2f}")
    elif price <= latest["lower"]:
        print(f"📉 {table} 最新价 {price} 触及布林下轨 {latest['lower']:.2f}")

    if khprice >= latest["upper"]:
        print(f"📈 {table} k线最高价 {khprice} 触及布林上轨 {latest['upper']:.2f}")
    elif klprice <= latest["lower"]:
        print(f"📉 {table} k线最低价 {klprice} 触及布林下轨 {latest['lower']:.2f}")        


def check_all_tables(db_path: str,symbol):
    """
    遍历数据库里所有kline表，检查布林突破
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 找出所有kline表
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{symbol}_%'")
    tables = [row[0] for row in cursor.fetchall()]

    print(tables)

    curPrice = get_current_price(symbol)

    for table in tables:
        check_bollinger_breakout(conn, table,curPrice)

    conn.close()


if __name__ == "__main__":
    update_all_symbol()
    for symbol in HOT_SYMBOLS:
        check_all_tables(DB_FILE,symbol)  # 这里换成你的数据库文件名
