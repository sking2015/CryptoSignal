import asyncio
import time
import htx_scaner
# import binance_scaner
# import RobotCtrl
from RobotNotifier import send_message_async

CHECK_INTERVAL = 60 * 15  # 秒，检查条件的间隔


async def main():
    while True:
        signalist = htx_scaner.checkSignal()
        message = ""

        for symbol in signalist:
            message +=  symbol
            message += "\n"

        if message:
            await send_message_async(message)

        await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())




