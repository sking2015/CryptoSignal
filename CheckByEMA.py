from ConstDef import g_ACD
import pandas as pd
import sqlite3
import sys

def check_ema_signals_by_database(conn, symbol,indexname: str,limit: int = 300):

    conn.row_factory = sqlite3.Row

    # 找出所有kline表
    cursor = conn.cursor()

    # 找出所有kline表
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{symbol}_%'")
    tables = [row[0] for row in cursor.fetchall()]

    for table in tables:
        print(f"检查{table}的k线数据")
        
        para = table.split("_")
        period = para[1]
        print(f"检查{symbol}的{period}线")      

        query = f'SELECT {indexname}, close, high, low FROM "{table}" ORDER BY {indexname} DESC LIMIT {limit+2}'
        df = pd.read_sql(query, conn).sort_values(indexname)
        print(df)
        if(len(df) > 200):
            detect_ema_signals(df,indexname)
        else:
            print(f"{table}不足200根,只有{len(df)}根")


def detect_ema_signals(df,indexname):
    """
    输入: df 必须包含 'close' 列 (float)
    输出: 返回近300根K线中的EMA信号
    """

    # 计算EMA
    df["EMA7"] = df["close"].ewm(span=7, adjust=False).mean()
    df["EMA25"] = df["close"].ewm(span=25, adjust=False).mean()
    df["EMA99"] = df["close"].ewm(span=99, adjust=False).mean()

    signals = []

    # 只检查最后300根    
    for i in range(1, len(df.tail(200))):
        row_prev = df.iloc[-200 + i - 1]
        row_curr = df.iloc[-200 + i]

        time = row_curr[indexname] if indexname in df.columns else i

        # === 短期 vs 中期 (EMA7 vs EMA25)
        if row_prev["EMA7"] <= row_prev["EMA25"] and row_curr["EMA7"] > row_curr["EMA25"]:
            signals.append((time, "金叉: EMA7 上穿 EMA25"))
        elif row_prev["EMA7"] >= row_prev["EMA25"] and row_curr["EMA7"] < row_curr["EMA25"]:
            signals.append((time, "死叉: EMA7 下穿 EMA25"))

        # === 短期 vs 长期 (EMA7 vs EMA99)
        if row_prev["EMA7"] <= row_prev["EMA99"] and row_curr["EMA7"] > row_curr["EMA99"]:
            signals.append((time, "金叉: EMA7 上穿 EMA99"))
        elif row_prev["EMA7"] >= row_prev["EMA99"] and row_curr["EMA7"] < row_curr["EMA99"]:
            signals.append((time, "死叉: EMA7 下穿 EMA99"))

        # === 中期 vs 长期 (EMA25 vs EMA99)
        if row_prev["EMA25"] <= row_prev["EMA99"] and row_curr["EMA25"] > row_curr["EMA99"]:
            signals.append((time, "金叉: EMA25 上穿 EMA99"))
        elif row_prev["EMA25"] >= row_prev["EMA99"] and row_curr["EMA25"] < row_curr["EMA99"]:
            signals.append((time, "死叉: EMA25 下穿 EMA99"))

    return signals


# 用法示例:
# df = pd.DataFrame(kline_data, columns=["time","open","high","low","close","volume"])
# df["close"] = df["close"].astype(float)
# signals = detect_ema_signals(df)
# for s in signals:
#     print(s)


if __name__ == "__main__":

    strExchange = "BINANCE"
    if len(sys.argv) > 1:
        if sys.argv[1] == "HTX":
            strExchange = "HTX"

    g_ACD.setExchange(strExchange)

    conn = sqlite3.connect(g_ACD.getDB())   

    check_ema_signals_by_database(conn,"BTCUSDT",g_ACD.getIndexName())

