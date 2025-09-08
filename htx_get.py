import requests
import pandas as pd
import pandas_ta as ta

import requests
import pandas as pd
import pandas_ta as ta


import requests
import pandas as pd
import pandas_ta as ta


def fetch_signals(symbol="ethusdt", period="30min", size=144, return_df=False):
    """
    拉取 HTX K线数据并计算 MACD、RSI、KDJ、BOLL、TD Sequential 指标
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
    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"], df["macd_signal"] = macd["MACD_12_26_9"], macd["MACDs_12_26_9"]

    # RSI
    df["rsi"] = ta.rsi(df["close"], length=14)

    # KDJ
    kdj = ta.stoch(df["high"], df["low"], df["close"], k=9, d=3, smooth_k=3)
    df["kdj_k"], df["kdj_d"] = kdj["STOCHk_9_3_3"], kdj["STOCHd_9_3_3"]
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    # 布林带
    boll = ta.bbands(df["close"], length=20, std=2)
    df["boll_upper"], df["boll_middle"], df["boll_lower"] = boll["BBU_20_2.0"], boll["BBM_20_2.0"], boll["BBL_20_2.0"]

    # TD Sequential 计数
    td_count = [0] * len(df)
    for i in range(4, len(df)):
        if df.loc[i, "close"] > df.loc[i - 4, "close"]:
            td_count[i] = td_count[i - 1] + 1 if td_count[i - 1] > 0 else 1
        elif df.loc[i, "close"] < df.loc[i - 4, "close"]:
            td_count[i] = td_count[i - 1] - 1 if td_count[i - 1] < 0 else -1
        else:
            td_count[i] = 0
    df["td_count"] = td_count

    if return_df:
        return df

    # === 4. 检查信号 ===
    signals_list = []
    BOLL_TREND_CONFIRM = 2  # 连续多少根K线才算趋势确认

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

        # BOLL 单根突破
        if row["close"] > row["boll_upper"]:
            signals.append("突破布林上轨")
        if row["close"] < row["boll_lower"]:
            signals.append("跌破布林下轨")

        # BOLL 趋势保持确认
        if i >= BOLL_TREND_CONFIRM:
            if all(df.loc[i - j, "close"] > df.loc[i - j, "boll_upper"] for j in range(BOLL_TREND_CONFIRM)):
                signals.append(f"布林带上轨突破确认（连续{BOLL_TREND_CONFIRM}根）")
            if all(df.loc[i - j, "close"] < df.loc[i - j, "boll_lower"] for j in range(BOLL_TREND_CONFIRM)):
                signals.append(f"布林带下轨突破确认（连续{BOLL_TREND_CONFIRM}根）")

        # TD Sequential
        if row["td_count"] == 9:
            signals.append("TD Sequential 九连上涨")
        if row["td_count"] == -9:
            signals.append("TD Sequential 九连下跌")

        if signals:
            signals_list.append({
                "time": row["time"],
                "close": row["close"],
                "signals": signals
            })

    # === 5. 打印最新收盘数据 ===
    latest = df.iloc[-1]
    print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, "
          f"KDJ_J={latest['kdj_j']:.2f}, TD_Count={latest['td_count']}")

    return signals_list





hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt"
]

# TIME = "30min"
# #scanlist(hot_symbols,TIME)


# def checkSignal():
#     return scanlist(hot_symbols,TIME)


