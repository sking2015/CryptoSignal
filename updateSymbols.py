import sqlite3
import requests
import pandas as pd

from ConstDef import ALL_CONST

def get_all_symbols_from_net(conn):
    url = ALL_CONST["api_symbols"]
    resp = requests.get(url)
    data = resp.json()
    if data["status"] == "ok":
        symbols = [item["symbol"] for item in data["data"]]
        symbolsdata = data["data"]
        # print("拉取结果",symbolsdata)

        df = pd.DataFrame(symbolsdata) 
        df = df[["symbol", "symbol-partition", "state", "api-trading"]]
        print("所有数据",df)
        
        if not df.empty:                        
            df.to_sql(ALL_CONST["Table_symbols"], conn, if_exists="replace", index=True)    
            print(f"已向数据库写入{len(df)}条数据")

        return symbols
    else:
        raise Exception(f"API error: {data}")
    
if __name__ == "__main__":
    conn = sqlite3.connect(ALL_CONST["DB"]) 
    symbols = get_all_symbols_from_net(conn)

    conn.close()

    print(f"交易对总数: {len(symbols)}")
    print("前10个交易对:", symbols[:10])
    # update_all_symbol()    
