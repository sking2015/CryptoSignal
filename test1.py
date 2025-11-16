import requests
import json

def get_btc_price():
    url = "https://api.hyperliquid.xyz/info"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {"type": "allMids"}
    
    res = requests.post(url, headers=headers, json=payload)
    print("状态码:", res.status_code)
    print("返回内容前500字:", res.text[:500])
    
    if res.status_code != 200 or not res.text:
        raise Exception("接口返回异常")
    
    data = res.json()
    print("解析后的数据:", data)
    
    if "BTC" not in data:
        raise Exception(f"未找到 BTC，所有 key: {list(data.keys())}")
    
    return float(data["BTC"])

if __name__ == "__main__":
    try:
        btc_price = get_btc_price()
        print(f"BTC 最新价格: {btc_price}")
    except Exception as e:
        print("获取 BTC 价格出错:", e)
