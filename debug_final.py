import sys
import os
import traceback
import asyncio
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

# Redirect stderr to file
sys.stderr = open("debug_log.txt", "w")

async def main():
    try:
        async with Client("debug_final", api_id=os.getenv("API_ID"), api_hash=os.getenv("API_HASH"), bot_token=os.getenv("BOT_TOKEN"), in_memory=True) as app:
            chat_id = int(os.getenv("STORAGE_CHANNEL_ID"))
            msg = await app.send_message(chat_id, "Debug Ping Final 🚀")
            print(f"SUCCESS: {msg.id}")
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
