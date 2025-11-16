import requests
import time
import json

def fetch_candles(coin: str, interval: str, limit: int, end_time_ms: int = None):
    """
    拉取 K 线数据 via candleSnapshot 接口。
    :param coin: 交易对资产标识，如 "BTC"
    :param interval: 时间周期，如 "1m"
    :param limit: 想要的根数（如 300）
    :param end_time_ms: 结束时间戳（毫秒），默认为当前时间
    :return: list of candle dicts
    """
    if end_time_ms is None:
        end_time_ms = int(time.time() * 1000)
    
    # interval 转换为分钟数
    minute_map = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "8h": 480, "12h": 720,
        "1d": 1440, "3d": 4320, "1w": 10080
    }
    if interval not in minute_map:
        raise ValueError(f"Unsupported interval: {interval}")
    
    span_ms = minute_map[interval] * limit * 60 * 1000
    start_time_ms = end_time_ms - span_ms

    url = "https://api.hyperliquid.xyz/info"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start_time_ms,
            "endTime": end_time_ms
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    if res.status_code != 200:
        raise Exception(f"接口返回状态码 {res.status_code}, 内容: {res.text}")

    data = res.json()
    if not isinstance(data, list):
        raise Exception(f"返回不是列表，内容: {data}")
    
    return data

def get_last_n_minutes_candles(coin: str, interval: str, n: int):
    """
    获取最近 n 根 interval 周期的 K 线。如果 n 超过一次请求上限（5000根），自动分页。
    """
    max_per_request = 5000
    all_candles = []
    end_time = int(time.time() * 1000)

    while len(all_candles) < n:
        remaining = n - len(all_candles)
        request_count = remaining if remaining <= max_per_request else max_per_request
        candles = fetch_candles(coin, interval, request_count, end_time)
        if not candles:
            break
        # 假设接口返回按时间升序排序（从旧到新）
        all_candles = candles + all_candles
        # 更新 end_time 为最旧 candle 的时间戳 - 1 毫秒，防止重复
        oldest = candles[0]
        end_time = oldest["t"] - 1
        time.sleep(0.2)  # 避免请求过快
        
    return all_candles[-n:]

if __name__ == "__main__":
    coin = "BTC"
    interval = "1m"
    n = 300

    try:
        candles = get_last_n_minutes_candles(coin, interval, n)
        print(f"共获取 {len(candles)} 根 {interval} K 线（{coin}）")
        # 打印最后 5 根做示例
        for bar in candles[-5:]:
            print(json.dumps(bar, indent=2, ensure_ascii=False))
    except Exception as e:
        print("出错:", e)
