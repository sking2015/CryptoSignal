# notifier.py
import asyncio
import time
from telegram import Bot

# ===================== 配置 =====================
TOKEN = "8414564044:AAHTT2sl9fzrMu6jG2dyax1IHdwsjrGLtlM"
CHAT_ID = "8052437792"  # 可以是你的个人ID或者群组ID
MESSAGE_INTERVAL = 60  # 秒，检查条件的间隔
# ===================== 模块内部状态 =====================
_bot_instance = None
_last_sent_time = 0

def _get_bot():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = Bot(token=TOKEN)
    return _bot_instance

async def send_message_async(text: str):
    global _last_sent_time
    bot = _get_bot()
    now = time.time()
    if now - _last_sent_time >= MESSAGE_INTERVAL:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=text)
            _last_sent_time = now
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 已发送:\n {text}")
        except Exception as e:
            print("发送消息出错:", e)
    else:
        print(f"间隔太短，消息未发送: {text}")

# ===================== 对外暴露函数 =====================
# def send_message(text: str):
#     """
#     同步调用的接口，传入要发送的文本即可。
#     内部使用 asyncio.run 调用异步发送。
#     """
#     asyncio.run(_send_message_async(text))
