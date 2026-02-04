import asyncio
import os
from dotenv import load_dotenv
from pyrogram import Client

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("STORAGE_CHANNEL_ID")

print(f"Checking Config...")
print(f"API_ID: {API_ID}")
print(f"BOT_TOKEN: {BOT_TOKEN[:10]}...")
print(f"CHANNEL_ID: {CHANNEL_ID}")

async def main():
    if not API_ID or not BOT_TOKEN or not CHANNEL_ID:
        print("ERROR: Missing env vars!")
        return

    print("Connecting to Telegram...")
    async with Client("test_uploader", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True) as app:
        print("Connected!")
        me = await app.get_me()
        print(f"Bot Name: {me.first_name} (@{me.username})")

        print(f"Attempting to upload to channel {CHANNEL_ID}...")
        try:
            # Create dummy file
            with open("test_upload.txt", "w") as f:
                f.write("This is a test upload from TeleCloud verification script.")

            msg = await app.send_document(
                int(CHANNEL_ID),
                document="test_upload.txt",
                caption="Test Upload 🚀"
            )
            print(f"SUCCESS! Message sent. ID: {msg.id}")
            print(f"Check channel {CHANNEL_ID} to see if it appeared.")
            
        except Exception as e:
            print(f"UPLOAD FAILED: {e}")
            if "peer" in str(e).lower():
                print("HINT: Is the channel ID correct? Does it need -100 prefix?")
                print("HINT: Is the Bot an ADMIN in the channel?")

if __name__ == "__main__":
    asyncio.run(main())
