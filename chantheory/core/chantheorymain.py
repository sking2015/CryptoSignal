
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取上级目录 (ChanLunBot) 的路径
parent_dir = os.path.dirname(current_dir)
# 构建 core 目录的路径
root_dir =  os.path.dirname(parent_dir)

# 将 core 目录加入到 Python 的搜索路径中
if root_dir not in sys.path:
    sys.path.append(root_dir)

from chantheoryScan import ChanLunStrategy
import asyncio
from datetime import datetime
from RobotNotifier import send_message_async

async def main():
    scanner = ChanLunStrategy()
    coins = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB']
    
    # 级别设置：可以根据需要调整
    main_lv = ['30m', '1h', '4h', '1d']
    sub_lv = ['5m', '15m', '1h', '4h']

    print("启动缠论全买卖点扫描系统 (1/2/3 类买卖点)...")
    
    # for coin in coins:
    #     try:
    #         # 扫描前4个级别组合
    #         for i in range(len(main_lv)): 
    #             scanner.detect_signals(coin, main_lv[i], sub_lv[i])
    #             await asyncio.sleep(0.5) 
                
    #     except Exception as e:
    #         print(f"处理 {coin} 时出错: {e}")
    #         print(traceback.format_exc())    

    last_run_hour = -1
    last_run_half = -1  # 0 表示整点，1 表示半点

    while True:
        now = datetime.now()
        minute = now.minute
        
        # 判断当前是否是整点/半点
        current_half = 0 if minute < 30 else 1 if minute >= 30 else None

        if last_run_hour != now.hour or last_run_half != current_half:       
            
            #每一次检查时清空消息
            msgstr = ""
            for coin in coins:
                try:
                    # 扫描前4个级别组合
                    for i in range(len(main_lv)): 
                        msgstr += scanner.detect_signals(coin, main_lv[i], sub_lv[i])
                        await asyncio.sleep(0.5) 
                        
                except Exception as e:
                    print(f"处理 {coin} 时出错: {e}")
                    print(traceback.format_exc())  


            if msgstr != "":
                 await send_message_async(msgstr)

            # 更新上一次执行记录
            last_run_hour = now.hour
            last_run_half = current_half            

        # 每秒检查一次，保证不会漏
        await asyncio.sleep(1)             

if __name__ == "__main__":
    asyncio.run(main())