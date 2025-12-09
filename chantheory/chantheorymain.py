
import sys
import os


current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取上级目录 (cropytscan 主目录，里面放了其它诸如机器人一类的模块) 的路径
parent_dir = os.path.dirname(current_dir)


# 将 core 目录加入到 Python 的搜索路径中
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# --- [路径修正] 确保能引用到 core 目录 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
core_dir = os.path.join(current_dir, 'core') 
if core_dir not in sys.path:
    sys.path.append(core_dir)    

from chantheoryScan import ChanLunStrategy
import asyncio
from datetime import datetime
from RobotNotifier import send_message_async
import traceback

async def main():
    scanner = ChanLunStrategy()
    coins = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB']
    
    # 级别设置：可以根据需要调整
    main_lv = ['30m', '1h', '4h', '1d']
    sub_lv = ['5m', '15m', '30m', '4h']

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

    last_5m = -1

    while True:
        now = datetime.now()
        minute = now.minute
        
        # 判断当前是否为5的倍数
        # print("当前分钟数",minute)
        # print("当前分钟数除以5",minute %5)

        if last_5m == -1 or minute %5 == 0:       
            
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
                #  await send_message_async(msgstr)
                print(msgstr)

            # 更新上一次执行记录            
            last_5m = minute
            print("最后的5分钟",last_5m)
                    

        # 每秒检查一次，保证不会漏
        await asyncio.sleep(1)             

if __name__ == "__main__":
    asyncio.run(main())