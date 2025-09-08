import requests

url = "https://api.huobi.pro/market/history/kline"
params = {
    "symbol": "ethusdt",
    "period": "30min",
    "size": 10
}

try:
    resp = requests.get(url, params=params, timeout=10)
    print(resp.status_code, resp.json())
except Exception as e:
    print("请求失败：", e)
