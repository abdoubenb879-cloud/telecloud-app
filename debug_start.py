import sys
import os
import traceback
import asyncio

# --- PATCH START ---
import pyrogram.utils
def patched_get_peer_type(peer_id: int) -> str:
    try:
        return pyrogram.utils.get_peer_type(peer_id)
    except ValueError:
        return "channel"
pyrogram.utils.get_peer_type = patched_get_peer_type
print("[PATCH] Applied.")
# --- PATCH END ---

from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("STORAGE_CHANNEL_ID")

async def main():
    print("STEP 1: Init")
    try:
        async with Client("debug_checker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True) as app:
            print("STEP 2: Connected")
            me = await app.get_me()
            print(f"Bot: {me.username}")
            
            chat_id = int(CHANNEL_ID)
            print(f"STEP 3: Sending to {chat_id}")
            msg = await app.send_message(chat_id, "Debug Ping with Patch 🚀")
            print(f"SUCCESS: {msg.id}")
            print(f"URL: https://t.me/c/{str(chat_id).replace('-100','')}/{msg.id}")
            
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
