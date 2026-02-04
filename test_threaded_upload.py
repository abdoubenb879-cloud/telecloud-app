"""
Threaded Local Upload Test Script
Replicates Render's multi-threaded environment.
"""
import os
import sys
import threading
import time
import tempfile

# Add the project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from app.telegram_client import get_bot_client

def upload_task(id):
    print(f"[THREAD-{id}] Starting...")
    # Create a small test file
    test_file = os.path.join(tempfile.gettempdir(), f"telecloud_test_{id}.txt")
    with open(test_file, "w") as f:
        f.write(f"TeleCloud Threaded Test {id}\n")
    
    try:
        bot = get_bot_client()
        print(f"[THREAD-{id}] Calling upload_file...")
        result = bot.upload_file(test_file)
        print(f"[THREAD-{id}] SUCCESS! Message ID: {result.id}")
    except Exception as e:
        print(f"[THREAD-{id}] FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

print("Starting 3 parallel upload threads...")
threads = []
for i in range(3):
    t = threading.Thread(target=upload_task, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print("ALL THREADS FINISHED.")
