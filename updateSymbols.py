import sqlite3
import requests
import pandas as pd
import sys

from ConstDef import g_ACD

def ProcessData_ByHTX(data):
    if data["status"] == "ok":
        # symbols = [item["symbol"] for item in data["data"]]
        symbolsdata = data["data"]
        # print("拉取结果",symbolsdata)

        df = pd.DataFrame(symbolsdata) 
        df = df[["symbol", "symbol-partition", "state", "api-trading"]]
        print("所有数据",df)        
        return df        
    else:
        raise Exception(f"API error: {data}")
    
def ProcessData_ByBinance(data):
    symbols = data.get("symbols", [])
    df = pd.DataFrame(symbols)

    # 只保留需要的字段
    wanted = ["symbol", "status", "baseAsset", "quoteAsset"]
    df = df[[c for c in wanted if c in df.columns]]

    # 筛选：状态为 TRADING 且 quoteAsset = USDT
    df = df[(df["status"] == "TRADING") & (df["quoteAsset"] == "USDT")]

    return df.reset_index(drop=True)    



def get_all_symbols_from_net(conn):
    url = g_ACD.getApiSymbols()
    resp = requests.get(url)
    data = resp.json()

    if g_ACD.getExchange == "HTX":
        df = ProcessData_ByHTX(data)
    else:
        # 除了HTX就是币安
        df = ProcessData_ByBinance(data)

    if not df.empty:                        
        df.to_sql(g_ACD.getTableSymbols(), conn, if_exists="replace", index=True)    
        print(f"已向数据库写入{len(df)}条数据")        

    
if __name__ == "__main__":
    
    strExchange = "BINANCE"
    if len(sys.argv) > 1:
        if sys.argv[1] == "HTX":
            strExchange = "HTX"

    g_ACD.setExchange(strExchange)
    conn = sqlite3.connect(g_ACD.getDB())     
    symbols = get_all_symbols_from_net(conn)

    conn.close()

    # update_all_symbol()    



