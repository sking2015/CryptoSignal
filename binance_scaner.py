import requests
import pandas as pd
import pandas_ta as ta

def fetch_binance_signals(symbol="ETHUSDT", interval="1h", limit=144, return_df=False):
    """
    拉取 Binance K线数据并计算 MACD、RSI、KDJ 指标
    参数:
        symbol: str, 交易对，如 "ETHUSDT"
        interval: str, K线周期，如 "30m", "1h", "1d"
        limit: int, 返回多少根 K线数据
        return_df: bool, True 返回 DataFrame，否则返回信号列表
    返回:
        DataFrame 或 信号列表
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"{symbol} 请求失败: {e}")
        return pd.DataFrame() if return_df else []

    # 转换为 DataFrame
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_base_vol","taker_quote_vol","ignore"
    ])

    # 转 float
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 转 UTC+8 时间
    df["time"] = pd.to_datetime(df["open_time"], unit="ms") + pd.Timedelta(hours=8)
    df = df.sort_values("time").reset_index(drop=True)

    # === 计算指标 ===
    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is None or macd.empty:
        df["macd"], df["macd_signal"] = [float('nan')]*len(df), [float('nan')]*len(df)
    else:
        df["macd"] = macd.get("MACD_12_26_9", [float('nan')]*len(df))
        df["macd_signal"] = macd.get("MACDs_12_26_9", [float('nan')]*len(df))

    # RSI
    rsi = ta.rsi(df["close"], length=14)
    df["rsi"] = rsi if rsi is not None else [float('nan')]*len(df)

    # KDJ
    kdj = ta.stoch(df["high"], df["low"], df["close"], k=9, d=3, smooth_k=3)
    if kdj is None or kdj.empty:
        df["kdj_k"], df["kdj_d"], df["kdj_j"] = [float('nan')]*len(df), [float('nan')]*len(df), [float('nan')]*len(df)
    else:
        df["kdj_k"] = kdj.get("STOCHk_9_3_3", [float('nan')]*len(df))
        df["kdj_d"] = kdj.get("STOCHd_9_3_3", [float('nan')]*len(df))
        df["kdj_j"] = 3*df["kdj_k"] - 2*df["kdj_d"]

    if return_df:
        return df

    # === 放宽条件信号判断 ===
    signals_list = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i-1], df.iloc[i]

        rsi_signal = ""
        if curr["rsi"] > 70:
            rsi_signal = "RSI 超买"
        elif curr["rsi"] < 30:
            rsi_signal = "RSI 超卖"

        # MACD 金叉/死叉
        macd_signal = ""
        if not pd.isna(prev["macd"]) and not pd.isna(prev["macd_signal"]):
            if prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]:
                macd_signal = "MACD 金叉"
            elif prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
                macd_signal = "MACD 死叉"

        # KDJ 金叉/死叉
        kdj_signal = ""
        if not pd.isna(prev["kdj_k"]) and not pd.isna(prev["kdj_d"]):
            if prev["kdj_k"] < prev["kdj_d"] and curr["kdj_k"] > curr["kdj_d"]:
                kdj_signal = "KDJ 金叉"
            elif prev["kdj_k"] > prev["kdj_d"] and curr["kdj_k"] < curr["kdj_d"]:
                kdj_signal = "KDJ 死叉"

        # 放宽条件
        if rsi_signal == "RSI 超卖" and (macd_signal == "MACD 金叉" or kdj_signal == "KDJ 金叉"):
            signals_list.append({"time": curr["time"], "close": curr["close"], "RSI": curr["rsi"], "KDJ_J": curr["kdj_j"], "signal": "买入"})
        elif rsi_signal == "RSI 超买" and (macd_signal == "MACD 死叉" or kdj_signal == "KDJ 死叉"):
            signals_list.append({"time": curr["time"], "close": curr["close"], "RSI": curr["rsi"], "KDJ_J": curr["kdj_j"], "signal": "卖出"})

    # 打印最新数据
    if not df.empty:
        latest = df.iloc[-1]
        print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}")

    return signals_list



def scanlist(list_hot,timedesc):
    signals_list = []
    for symbol in list_hot:
        print(f"\n=== {symbol.upper()} 信号 ===")
        bHavesign = False
        
        # 调用已有函数获取 DataFrame
        df = fetch_binance_signals(symbol=symbol.upper(), interval=timedesc, limit=288, return_df=True)  
        # 这里假设 fetch_htx_signals 支持 return_df=True 返回 DataFrame 而不是 signals 列表

        for i in range(1, len(df)):
            prev, curr = df.iloc[i-1], df.iloc[i]

            # 买入信号
            if (curr["rsi"] < 30 # RSI 超卖
                and (prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]  # MACD 金叉                                
                or prev["kdj_k"] < prev["kdj_d"] and curr["kdj_k"] > curr["kdj_d"])):  # KDJ 金叉
                print(f"{curr['time']} 买入信号 | 收盘价={curr['close']:.2f}, RSI={curr['rsi']:.2f}, KDJ_J={curr['kdj_j']:.2f}")
                bHavesign = True

            # 卖出信号
            if ( curr["rsi"] > 70 # RSI 超买
                and (prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]  # MACD 死叉                                        
                or prev["kdj_k"] > prev["kdj_d"] and curr["kdj_k"] < curr["kdj_d"])):  # KDJ 死叉
                print(f"{curr['time']} 卖出信号 | 收盘价={curr['close']:.2f}, RSI={curr['rsi']:.2f}, KDJ_J={curr['kdj_j']:.2f}")
                bHavesign = True

        # 打印最新收盘价及指标
        if (bHavesign):
            print("该币种有买卖信号，请详阅复盘")
        latest = df.iloc[-1]
        print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}")

        # 最新一条数据额外检查
        latest = df.iloc[-1]
        latest_prev = df.iloc[-2]

        # RSI 超买/超卖
        latest_rsi_signal = ""
        if latest["rsi"] > 70:
            latest_rsi_signal = "RSI 超买"
        elif latest["rsi"] < 30:
            latest_rsi_signal = "RSI 超卖"

        # MACD 金叉/死叉
        latest_macd_signal = ""
        if latest_prev["macd"] < latest_prev["macd_signal"] and latest["macd"] > latest["macd_signal"]:
            latest_macd_signal = "MACD 金叉"
        elif latest_prev["macd"] > latest_prev["macd_signal"] and latest["macd"] < latest["macd_signal"]:
            latest_macd_signal = "MACD 死叉"

        # KDJ 金叉/死叉
        latest_kdj_signal = ""
        if latest_prev["kdj_k"] < latest_prev["kdj_d"] and latest["kdj_k"] > latest["kdj_d"]:
            latest_kdj_signal = "KDJ 金叉"
        elif latest_prev["kdj_k"] > latest_prev["kdj_d"] and latest["kdj_k"] < latest["kdj_d"]:
            latest_kdj_signal = "KDJ 死叉"

        # 判断最新数据是否触发买卖信号
        if (latest_rsi_signal and (latest_kdj_signal)) or latest_macd_signal:        
            signal = f"{symbol.upper()} 最新数据触发买卖信号！ 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}"
            print(f"\n>>> " + signal )  
            signals_list.append(signal)

    return signals_list        


hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt"
]

TIME = "15m"
#scanlist(hot_symbols,TIME)
#TIME = "5min"
#scanlist(hot_symbols,TIME)


def checkSignal():
    return scanlist(hot_symbols,TIME)