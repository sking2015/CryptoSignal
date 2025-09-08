import asyncio
import time
# from htx_get import fetch_signals
from Scaner import scanlist
import datetime
# import binance_scaner
# import RobotCtrl
from RobotNotifier import send_message_async

BASE = 60

CHECK_INTERVAL = BASE * 60  # 秒，检查条件的间隔

hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt"
]

TIME = f"{BASE}min"


async def main():
    while True:      
        signalist = scanlist(hot_symbols,TIME)
        message = ""

        for symbol in signalist:
            message +=  symbol
            message += "\n"

        if message:
            await send_message_async(message)

        await asyncio.sleep(CHECK_INTERVAL)


        
async def main1():


    last_run_hour = -1
    last_run_half = -1  # 0 表示整点，1 表示半点

    while True:
        now = datetime.time()
        minute = now.minute

        # 判断是否应该执行
        if minute == 0:
            current_half = 0
        elif minute == 30:
            current_half = 1
        else:
            current_half = None

        if current_half is not None:
            if last_run_hour != now.hour or last_run_half != current_half:
                # 执行任务
                signalist = scanlist(hot_symbols, TIME)
                message = "\n".join(signalist)
                if message:
                    await send_message_async(message)

                # 更新上一次执行记录
                last_run_hour = now.hour
                last_run_half = current_half

        # 每秒检查一次，保证不会漏
        await asyncio.sleep(1)



asyncio.run(main1())




