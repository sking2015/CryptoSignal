import asyncio
from telegram import Bot

# TOKEN = "8414564044:AAHTT2sl9fzrMu6jG2dyax1IHdwsjrGLtlM"
TOKEN = "8245368359:AAGv1GSxYTwo9BeQ0G0DC7ytvDZQgiEVVzE"

async def main():
    bot = Bot(token=TOKEN)

    updates = await bot.get_updates()  # 注意这里要 await

    if not updates:
        print("目前没有收到消息，请先给机器人发送一条消息")
    else:
        for update in updates:
            chat = update.message.chat
            text = update.message.text
            print(f"用户名: {chat.username}")
            print(f"Chat ID: {chat.id}")
            print(f"text: {text}")          
    
    await bot.close()

if __name__ == "__main__":
    asyncio.run(main())



# Done! Congratulations on your new bot. You will find it at t.me/Remind_20250908_Bot. You can now add a description, about section and profile picture for your bot, see /help for a list of commands. By the way, when you've finished creating your cool bot, ping our Bot Support if you want a better username for it. Just make sure the bot is fully operational before you do this.

# Use this token to access the HTTP API:
# 8414564044:AAHTT2sl9fzrMu6jG2dyax1IHdwsjrGLtlM
# Keep your token secure and store it safely, it can be used by anyone to control your bot.

# For a description of the Bot API, see this page: https://core.telegram.org/bots/api