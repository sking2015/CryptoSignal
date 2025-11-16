import requests
import pandas as pd
import time

def fetch_candles(coin="BTC", interval="5m", limit=14):
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
            "startTime": 0,
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

if __name__ == "__main__":
    coin = "BTC"
    interval = "5m"  # 改为5分钟K线
    period = 14      # RSI周期

    try:
        closes = fetch_candles(coin=coin, interval=interval, limit=period)
        print("收盘价:", closes)
        rsi_value = compute_rsi(closes, period=period)
        print(f"最新 {interval} RSI 值: {rsi_value}")
    except Exception as e:
        print("出错:", e)

def main():
    fetch_candles("BTC","1m",101)
    fetch_candles("BTC","5m",101)
    fetch_candles("BTC","15m",101)


main()