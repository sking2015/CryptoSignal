import sqlite3
import requests
import pandas as pd
import time

from ConstDef import ALL_CONST
from DatabaseUpdate import update_all_kline


def update_all_symbols_kline(conn):
    conn.row_factory = sqlite3.Row
    cursorSymbols = conn.cursor()
    cursorSymbols.execute(f"SELECT symbol,state FROM {ALL_CONST['Table_symbols']}")

    onlineNum = 0
    for row in iter(cursorSymbols.fetchone, None):
        symbol = row["symbol"]
        state = row["state"] 
        print(symbol,state)
        if state == "online":
            onlineNum += 1
            update_all_kline(symbol,conn)
            time.sleep(1) 

    print("有效交易对：",onlineNum)

if __name__ == "__main__":
    conn = sqlite3.connect(ALL_CONST["DB"])     

    print("遍历所有symbols....")
    symbols = update_all_symbols_kline(conn)

    conn.close()
    # update_all_symbol()    
