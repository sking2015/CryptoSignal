import requests
import pandas as pd
import time
from RobotNotifier import send_message_async
import asyncio

def fetch_candles(coin="BTC", interval="1m", limit=14):
    """
    拉取最近 limit 根 K 线数据
    """
    url = "https://api.hyperliquid.xyz/info"
    headers = {"Content-Type": "application/json"}
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": 0,       # 可以根据需要调整分页逻辑
            "endTime": 9999999999999
        }
    }
    res = requests.post(url, headers=headers, json=payload)
    data = res.json()
    
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError("返回的 K 线数据为空，请检查 API 或参数")
    
    closes = [float(candle["c"]) for candle in data[-limit:]]
    return closes

def compute_rsi(prices, period=14):
    """
    计算 RSI（稳定版）
    """
    if len(prices) < 2:
        return None

    series = pd.Series(prices)
    deltas = series.diff()

    ups = deltas.clip(lower=0)
    downs = -deltas.clip(upper=0)

    roll_up = ups.rolling(period, min_periods=1).mean()
    roll_down = downs.rolling(period, min_periods=1).mean()

    RS = roll_up / roll_down.replace(0, pd.NA)
    RSI = 100 - (100 / (1 + RS))

    latest_rsi = RSI.iloc[-1]
    if pd.isna(latest_rsi):
        latest_rsi = 50.0  # 全平盘中性值
    return round(latest_rsi, 2)

def get(coin = "BTC",interval = "15m",period = 14 ):
    try:
        closes = fetch_candles(coin=coin, interval=interval, limit=period)
        # print("收盘价:", closes)
        rsi_value = compute_rsi(closes, period=period)
        if rsi_value >= 70 or rsi_value<=30:
            text = f"最新 {interval} RSI 值: {rsi_value}"
            return text
        else:
            return "" 
    except Exception as e:
        print("出错:", e)
        return ""

def get1_5_15():
    text = get("BTC","1m",14)
    if text != "" :
        text += "\n"
        text += get("BTC","5m",14) +"\n"
        text += get("BTC","15m",14)+"\n"
        asyncio.run(send_message_async(text))

if __name__ == "__main__":
    while True:
        get1_5_15()
        time.sleep(60)