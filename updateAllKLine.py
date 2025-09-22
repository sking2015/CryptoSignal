import sqlite3
import requests
import pandas as pd
import time
import sys

from ConstDef import g_ACD
from DatabaseUpdate import update_all_kline


def update_all_symbols_kline(conn):
    conn.row_factory = sqlite3.Row
    cursorSymbols = conn.cursor()


    onlineNum = 0
    if g_ACD.getExchange == "HTX":
        cursorSymbols.execute(f"SELECT symbol,state FROM {g_ACD.getTableSymbols()}")

        
        for row in iter(cursorSymbols.fetchone, None):                      
            state = row["state"] 
            print(symbol,state)
            if state == "online":
                symbol = row["symbol"]
                onlineNum += 1
                update_all_kline(symbol,conn)
                time.sleep(1) 
    else:
        cursorSymbols.execute(f"SELECT symbol FROM {g_ACD.getTableSymbols()}")
        symbols = [row[0] for row in cursorSymbols.fetchall()]         
        for symbol in symbols:                           
            print(f"{symbol}写表")
            update_all_kline(symbol,conn)
            onlineNum += 1
            time.sleep(1)   
                   
        

    print("有效交易对：",onlineNum)

if __name__ == "__main__":

    strExchange = "BINANCE"
    if len(sys.argv) > 1:
        if sys.argv[1] == "HTX":
            strExchange = "HTX"

    g_ACD.setExchange(strExchange)

    conn = sqlite3.connect(g_ACD.getDB())     

    print("遍历所有symbols....")
    symbols = update_all_symbols_kline(conn)

    conn.close()
    # update_all_symbol()    
