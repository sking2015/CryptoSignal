import sqlite3
import requests
import asyncio
import time
from datetime import datetime
import pandas as pd
from RobotNotifier import send_message_async
from Common import InitEnvironment,save_simple,load_number_default
from ConstDef import g_ACD
from CheckbyBoll import check_bollinger_convergence,check_bollinger_convergence_debug
from updateAllKLine import update_all_kline

import sys
import signal



def check_data4OneTable(conn, table: str):
    df = pd.read_sql(f'SELECT * FROM "{table}" ORDER BY open_time', conn)
    # 检查是否收敛
    # check_bollinger_convergence_debug(df)
    return check_bollinger_convergence(df)      


async def check_all_tables(conn,symbol):
    """
    遍历数据库里所有kline表，检查布林突破
    """
    cursor = conn.cursor()

    # 找出所有kline表
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{symbol}_%'")
    tables = [row[0] for row in cursor.fetchall()]

    # print(tables)


    # 在多少时间段上处于收敛
    count = 0
    mess = ""
    for table in tables:
        print(f"检查{table}的k线数据")
        
        para = table.split("_")
        period = para[1]
        print(f"检查{symbol}的{period}线")      
        if check_data4OneTable(conn,table):
            count += 1
            print(f"{symbol}在{period}线级别收敛")
            mess += period
            mess += " "


    if count > 0:
        strMess = f"{symbol} 在以下时间线上收敛:[{mess}]"
        await send_message_async(strMess)
    return count,mess

                                  


async def TimerTask(conn):

 

    conn.row_factory = sqlite3.Row
    cursorSymbols = conn.cursor()

    lastindex = load_number_default("lastIndex.txt",0)


    onlineNum = 0

    cursorSymbols.execute(f'SELECT "index",symbol FROM {g_ACD.getTableSymbols()} WHERE "index">= {lastindex}')
    symbols = [row[:2] for row in cursorSymbols.fetchall()]         
    # for symbol in symbols:                           
    #     print(f"准备检查交易对{symbol}")        
    #     onlineNum += 1  
    #     save_simple(symbol[0],"lastIndex.txt")
    #     time.sleep(0.1)


    sMess = ""    
    for row in symbols:   
        lastindex = row[0]
        symbol = row[1]
        print(symbol)
        time.sleep(0.1) 


        if symbol == "USDCUSDT" or symbol == "USD1USDT":
            # 稳定币交易对忽略
            continue 

        update_all_kline(symbol,conn)
        count,submess = await check_all_tables(conn,symbol)
        save_simple(lastindex,"lastIndex.txt")
        if count > 0:           
            sMess += " "
            sMess += f"{symbol}:{count}:[{submess}]"
            sMess += "\r\n"

    if sMess != "":
        print("===========================================")  
        message = "📉本轮共检测出以下币种触发量化信号，请关注：\n" + sMess    
        # print(message)
        await send_message_async(message)   

    # 全部执行完了要从新开始
    save_simple(0,"lastIndex.txt")

    print(f"共检查{onlineNum}对交易对")   




def handler(sig, frame):
    print("\n检测到 Ctrl+C，程序已安全退出。")    
    sys.exit(0)




def main():
    print("开始进入定时任务，执行完后休息一秒执行下一次")
    # 绑定 SIGINT 信号（Ctrl+C）
    signal.signal(signal.SIGINT, handler)  


    conn = sqlite3.connect(g_ACD.getDB())   
    # asyncio.run(TimerTask(conn))

    while True:
        asyncio.run(TimerTask(conn))            
        time.sleep(1) 
    
 
def Test():
    conn = sqlite3.connect(g_ACD.getDB())   
    asyncio.run(TimerTask(conn))
    conn.close()


if __name__ == "__main__":
    # asyncio.run(main())
    InitEnvironment()
    main()
        



      