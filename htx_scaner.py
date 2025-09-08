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

    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    # 转换为 DataFrame
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_base_vol","taker_quote_vol","ignore"
    ])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms") + pd.Timedelta(hours=8)  # 转 UTC+8
    df = df.sort_values("time").reset_index(drop=True)

    # === 计算指标 ===
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"], df["macd_signal"] = macd["MACD_12_26_9"], macd["MACDs_12_26_9"]
    df["rsi"] = ta.rsi(df["close"], length=14)
    kdj = ta.stoch(df["high"], df["low"], df["close"], k=9, d=3, smooth_k=3)
    df["kdj_k"], df["kdj_d"] = kdj["STOCHk_9_3_3"], kdj["STOCHd_9_3_3"]
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    if return_df:
        return df

    # === 放宽条件信号判断 ===
    signals_list = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i-1], df.iloc[i]

        # RSI 超买/超卖
        rsi_signal = ""
        if curr["rsi"] > 70:
            rsi_signal = "RSI 超买"
        elif curr["rsi"] < 30:
            rsi_signal = "RSI 超卖"

        # MACD 金叉/死叉
        macd_signal = ""
        if prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]:
            macd_signal = "MACD 金叉"
        elif prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
            macd_signal = "MACD 死叉"

        # KDJ 金叉/死叉
        kdj_signal = ""
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
    latest = df.iloc[-1]
    print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}")

    return signals_list

def fetch_htx_signals(symbol="ethusdt", period="30min", size=144, return_df=False):
    """
    拉取 HTX K线数据并计算 MACD、RSI、KDJ 指标

    参数:
        symbol: str, 交易对，如 "ethusdt"
        period: str, K线周期，如 "30min", "1h", "1day"
        size: int, 返回多少根 K线数据
        return_df: bool, True 则返回完整 DataFrame，False 则返回信号列表

    返回:
        如果 return_df=True: pandas.DataFrame
        否则: list of dict，每条 dict 包含时间、收盘价、信号说明
    """

    # === 1. 获取 HTX K线数据 ===
    url = "https://api.huobi.pro/market/history/kline"
    params = {
        "symbol": symbol,
        "period": period,
        "size": size
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    if data.get("status") != "ok":
        raise ValueError(f"API返回错误: {data}")

    # === 2. 转换为 DataFrame ===
    df = pd.DataFrame(data["data"])
    df["time"] = pd.to_datetime(df["id"], unit="s") + pd.Timedelta(hours=8)  # 转 UTC+8
    df = df.sort_values("time").reset_index(drop=True)

    # === 3. 计算指标 ===
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"], df["macd_signal"] = macd["MACD_12_26_9"], macd["MACDs_12_26_9"]
    df["rsi"] = ta.rsi(df["close"], length=14)
    kdj = ta.stoch(df["high"], df["low"], df["close"], k=9, d=3, smooth_k=3)
    df["kdj_k"], df["kdj_d"] = kdj["STOCHk_9_3_3"], kdj["STOCHd_9_3_3"]
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    if return_df:
        return df

    # === 4. 检查信号 ===
    signals_list = []
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        signals = []

        # MACD 金叉 / 死叉
        if prev["macd"] < prev["macd_signal"] and row["macd"] > row["macd_signal"]:
            signals.append("MACD 金叉")
        if prev["macd"] > prev["macd_signal"] and row["macd"] < row["macd_signal"]:
            signals.append("MACD 死叉")

        # RSI 超买/超卖
        if row["rsi"] > 70:
            signals.append("RSI 超买 (>70)")
        if row["rsi"] < 30:
            signals.append("RSI 超卖 (<30)")

        # KDJ 金叉 / 死叉
        if prev["kdj_k"] < prev["kdj_d"] and row["kdj_k"] > row["kdj_d"]:
            signals.append("KDJ 金叉")
        if prev["kdj_k"] > prev["kdj_d"] and row["kdj_k"] < row["kdj_d"]:
            signals.append("KDJ 死叉")

        # J线极端信号
        if row["kdj_j"] > 100:
            signals.append("KDJ_J 严重超买 (>100)")
        if row["kdj_j"] < 0:
            signals.append("KDJ_J 严重超卖 (<0)")

        if signals:
            signals_list.append({
                "time": row["time"],
                "close": row["close"],
                "signals": signals
            })

    # === 5. 打印最新收盘数据 ===
    latest = df.iloc[-1]
    print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}")

    return signals_list


def scanlist(list_hot,timedesc):
    signals_list = []
    for symbol in list_hot:
        print(f"\n=== {symbol.upper()} 信号 ===")
        bHavesign = False
        
        # 调用已有函数获取 DataFrame
        df = fetch_htx_signals(symbol=symbol, period=timedesc, size=288, return_df=True)  
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


        

        # 最新一条数据额外检查
        latest = df.iloc[-1]
        latest_prev = df.iloc[-2]

        print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}")        

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
        if (latest_rsi_signal and latest_kdj_signal) or latest_macd_signal:        
            signal = f"{symbol.upper()} 最新数据触发买卖信号！ 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}"
            if latest_rsi_signal:
                signal += latest_rsi_signal
                signal += " "
                signal += latest_kdj_signal
                signal += " "
            if latest_macd_signal:
                signal += latest_macd_signal

            print(f"\n>>> " + signal )  
            signals_list.append(signal)

    return signals_list



hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt"
]

TIME = "5min"
#scanlist(hot_symbols,TIME)


def checkSignal():
    return scanlist(hot_symbols,TIME)


