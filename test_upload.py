"""
Local Upload Test Script - BotPool version
"""
import os
import sys
import tempfile

# Add the project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("TELEGRAM UPLOAD TEST (BotPool)")
print("=" * 60)

try:
    from app.telegram_client import get_bot_client
    from app.config import Config
    
    bot = get_bot_client()
    print(f"BotPool initialized with {len(bot.bots)} bots")
    
    print("\nConnecting bots...")
    bot.connect()
    
except Exception as e:
    print(f"ERROR initializing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("STEP 2: Create Test File")
print("=" * 60)

test_file = os.path.join(tempfile.gettempdir(), "telecloud_pool_test.txt")
with open(test_file, "w") as f:
    f.write(f"TeleCloud BotPool Test\nTimestamp: {__import__('datetime').datetime.now()}\n")

print(f"Created test file: {test_file}")

print("\n" + "=" * 60)
print("STEP 3: Upload Test File")
print("=" * 60)

try:
    result = bot.upload_file(test_file)
    print(f"\n*** UPLOAD SUCCESSFUL! ***")
    print(f"Message ID: {result.id}")
    print(f"Bot used: {result.from_user.username if result.from_user else 'Bot'}")
except Exception as e:
    print(f"\n*** UPLOAD FAILED! ***")
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    if os.path.exists(test_file):
        os.remove(test_file)

print("\n" + "=" * 60)
print("TEST COMPLETE!")
bot.stop()
print("=" * 60)
