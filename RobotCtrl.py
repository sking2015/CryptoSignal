import time
import asyncio
from telegram import Bot

# ===================== 配置 =====================
TOKEN = "8414564044:AAHTT2sl9fzrMu6jG2dyax1IHdwsjrGLtlM"
CHAT_ID = "8052437792"  # 可以是你的个人ID或者群组ID
CHECK_INTERVAL = 60  # 秒，检查条件的间隔

bot = Bot(token=TOKEN)

# ===================== 自定义条件函数 =====================
def check_condition():
    """
    返回 True 表示触发提醒
    这里你可以写你自己的逻辑，例如：
    - 查询数据库
    - 检查文件
    - 获取API数据
    """
    # 示例：简单计数触发
    import random
    return random.random() > 0.8  # 20%概率触发

# ===================== 主循环 =====================


async def main():
    bot = Bot(token=TOKEN)

    # 异步发送消息
    await bot.send_message(chat_id=CHAT_ID, text="⚠️ 条件触发提醒！")

    await bot.close()

if __name__ == "__main__":
    asyncio.run(main())


# def main():
#     print("提醒系统启动...")
#     await bot.send_message(chat_id=CHAT_ID, text="⚠️ 条件触发提醒！")
#     # while True:
#     #     try:
#     #         if check_condition():
#     #             bot.send_message(chat_id=CHAT_ID, text="⚠️ 条件触发提醒！")
#     #             print("已发送提醒")
#     #         else:
#     #             print("条件未触发")
#     #     except Exception as e:
#     #         print("发送消息出错:", e)
#     #     time.sleep(CHECK_INTERVAL)

# if __name__ == "__main__":
#     main()
