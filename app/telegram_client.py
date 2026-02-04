import asyncio
import os
import sys
import threading
# Apply patch before importing Client
import app.pyrogram_patch
from pyrogram import Client
from .config import Config

# Shared background loop for all users/clients in THIS process
_loop = None
_loop_thread = None
_loop_ready = threading.Event()
_loop_lock = threading.Lock()

def ensure_loop_running():
    global _loop, _loop_thread
    
    # 1. Start if never started
    with _loop_lock:
        start_needed = False
        if _loop_thread is None:
            start_needed = True
            print("[LOOP] Starting Event Loop thread for the first time...")
        elif not _loop_thread.is_alive():
            start_needed = True
            print("[LOOP] CRITICAL: Event Loop thread died! Restarting...")
            
        if start_needed:
            # Reset state
            _loop_ready.clear()
            
            def run_loop():
                global _loop
                try:
                    _loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(_loop)
                    _loop_ready.set()
                    print(f"[LOOP] Loop {_loop} running in thread {threading.current_thread().name}")
                    _loop.run_forever()
                except Exception as e:
                    print(f"[LOOP] Loop crashed: {e}")

            _loop_thread = threading.Thread(target=run_loop, name="TeleCloudLoop", daemon=True)
            _loop_thread.start()
            
            # Wait for startup
            if not _loop_ready.wait(timeout=30):
                raise RuntimeError("Failed to start event loop thread")
        
        return _loop

class TelegramCloud:
    """Dynamic Telegram client meant to be instantiated per user session."""
    # ... (Keep existing implementation logic if possible, or minimal changes) ...
    # CHECK: TelegramCloud isn't the main issue, BotClient is. 
    # But for safety, TelegramCloud should also use the new ensure_loop_running
    
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        ensure_loop_running() 
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        
        # NOTE: If loop restarts, old TelegramCloud instances die. 
        # But they are usually short-lived in this app (created per request scope? No, looks like mostly BotClient is used).
        
        if session_string:
            async def create_cloud_client():
                return Client(
                    "telecloud_client", 
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    session_string=session_string,
                    in_memory=True,
                    no_updates=True
                )
            future = asyncio.run_coroutine_threadsafe(create_cloud_client(), _loop)
            self.client = future.result(timeout=10)
        else:
            async def create_local_client():
                return Client(
                    Config.SESSION_NAME,
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    workdir=Config.BASE_DIR,
                    no_updates=True
                )
            future = asyncio.run_coroutine_threadsafe(create_local_client(), _loop)
            self.client = future.result(timeout=10)
        
        self._connected = False
        self._resolved_chat_id = None
        self.storage_chat_title = "My Cloud Storage"

    def _run_async(self, coro_or_func):
        # ... (keep existing) ...
        print(f"[ASYNC] Submitting work to loop {_loop}...")
        if asyncio.iscoroutine(coro_or_func):
            coro = coro_or_func
        else:
            coro = coro_or_func()
            
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        try:
            return future.result(timeout=60) # Standard timeout
        except Exception as e:
            print(f"[ASYNC] ERROR: {e}")
            raise

    # ... (rest of methods standard) ...
    def connect(self):
        if not self._connected:
            async def work(): await self.client.start()
            self._run_async(work)
            self._connected = True
            self._resolve_chat()
        return self

    def stop(self):
        if self._connected:
            async def work(): await self.client.stop()
            self._run_async(work)
            self._connected = False

    def _resolve_chat(self):
        try:
            async def work(): return await self.client.get_chat(self.storage_chat)
            chat = self._run_async(work)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Private Chat')
        except Exception:
            async def work_me(): return await self.client.get_chat("me")
            chat = self._run_async(work_me)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = "Saved Messages"

    def upload_file(self, file_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        async def work():
            return await self.client.send_document(target, document=file_path, file_name=os.path.basename(file_path), progress=progress_callback)
        return self._run_async(work)

    def download_file(self, message_id, output_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        async def get_msg(): return await self.client.get_messages(target, message_id)
        message = self._run_async(get_msg)
        if not message or not message.document: raise Exception("File not found.")
        async def dl(): return await self.client.download_media(message, file_name=output_path, progress=progress_callback)
        return self._run_async(dl)

    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        async def work(): await self.client.delete_messages(target, message_id)
        self._run_async(work)

    def download_media(self, message_id, in_memory=False):
        target = self._resolved_chat_id or self.storage_chat
        async def work():
            msg = await self.client.get_messages(target, message_id)
            if not msg or not msg.document: return None
            return await self.client.download_media(msg, in_memory=in_memory)
        return self._run_async(work)

    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        ensure_loop_running()
        async def work():
            temp_client = Client(":memory:", api_id=api_id, api_hash=api_hash, in_memory=True)
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
        return asyncio.run_coroutine_threadsafe(work(), _loop).result(timeout=60)

    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        ensure_loop_running()
        async def work():
            await temp_client.sign_in(phone, code_hash, code)
            session_str = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            return session_str, me.id
        return asyncio.run_coroutine_threadsafe(work(), _loop).result(timeout=60)


# ============================================================================
# BOT CLIENT - Centralized storage using a single bot account
# ============================================================================

class BotClient:
    """
    Singleton Bot client.
    Handles auto-recovery if the background event loop dies.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.bot_token = Config.BOT_TOKEN
        self.channel_id = Config.STORAGE_CHANNEL_ID
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        
        self._create_client_on_loop()
        self._initialized = True
        print("[BOT] BotClient initialized successfully")

    def _create_client_on_loop(self):
        """Creates or Re-creates the Pyrogram client on the current active loop."""
        ensure_loop_running()
        
        print("[BOT] Creating Pyrogram Client...")
        async def create_bot():
            return Client(
                "telecloud_bot",
                api_id=self.api_id,
                api_hash=self.api_hash,
                bot_token=self.bot_token,
                in_memory=True,
                no_updates=True
            )
        
        future = asyncio.run_coroutine_threadsafe(create_bot(), _loop)
        self.client = future.result(timeout=30)
        self._connected = False
        self._loop_id = id(_loop) # Track which loop this client belongs to

    def _ensure_health(self):
        """Checks if loop is alive and matches our client. Restores if needed."""
        global _loop, _loop_thread
        
        is_dead = _loop_thread is None or not _loop_thread.is_alive()
        loop_changed = id(_loop) != self._loop_id if _loop else True
        
        if is_dead or loop_changed:
            print(f"[BOT-FIX] Detected issue! Dead={is_dead}, Changed={loop_changed}. Recovering...")
            
            # 1. Restart Loop (thread)
            ensure_loop_running()
            
            # 2. Re-create Client (bind to new loop)
            # Check ID again to be sure
            if id(_loop) != self._loop_id:
                print("[BOT-FIX] Loop ID changed. Recreating client...")
                self._create_client_on_loop()
                
                # 3. Auto-Connect if we were supposed to be connected
                print("[BOT-FIX] Reconnecting...")
                self.connect()

    def _run_async(self, coro):
        """Run async operation with auto-recovery."""
        self._ensure_health()
        
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        try:
            return future.result(timeout=300) # 5 minutes timeout
        except Exception as e:
            print(f"[BOT-ERROR] Async task failed: {e}")
            raise

    def connect(self):
        with BotClient._lock:
            if not self._connected:
                async def work():
                    try:
                        await self.client.start()
                    except Exception as e:
                        # Check for FloodWait without importing pyrogram everywhere
                        if "FLOOD_WAIT" in str(e):
                            import re
                            # Extract seconds from "A wait of X seconds is required" or similar
                            match = re.search(r'wait of (\d+) seconds', str(e))
                            wait_time = int(match.group(1)) if match else 60
                            print(f"[BOT-CRITICAL] 🛑 TELEGRAM RATE LIMIT. Must wait {wait_time}s.")
                            if wait_time > 300:
                                print("[BOT] Waiting > 5 mins. This might take a while...")
                            await asyncio.sleep(wait_time)
                            await self.client.start()
                        else:
                            raise e

                self._run_async(work())
                self._connected = True
                print(f"[BOT] Connected to channel {self.channel_id}")
        return self
    
    def stop(self):
        if self._connected:
            async def work(): await self.client.stop()
            self._run_async(work())
            self._connected = False
    
    def upload_file(self, file_path, progress_callback=None):
        async def work():
            return await self.client.send_document(self.channel_id, document=file_path, file_name=os.path.basename(file_path), progress=progress_callback)
        return self._run_async(work())
    
    def download_file(self, message_id, output_path, progress_callback=None):
        async def work():
            msg = await self.client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document: raise Exception("File not found")
            return await self.client.download_media(msg, file_name=output_path, progress=progress_callback)
        return self._run_async(work())
    
    def delete_message(self, message_id):
        async def work(): await self.client.delete_messages(self.channel_id, message_id)
        self._run_async(work())
    
    def download_media(self, message_id, in_memory=False):
        async def work():
            msg = await self.client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document: return None
            return await self.client.download_media(msg, in_memory=in_memory)
        return self._run_async(work())

    def get_file_range(self, message_id, offset, limit):
        async def work():
            msg = await self.client.get_messages(str(self.channel_id), message_id)
            if not msg or not msg.document: return None
            chunk = b""
            async for data in self.client.stream_media(msg, offset=offset, limit=limit):
                chunk += data
            return chunk
        return self._run_async(work())

    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        async def download_single(msg_id):
            msg = await self.client.get_messages(self.channel_id, msg_id)
            if not msg or not msg.document: return None
            return await self.client.download_media(msg, in_memory=False)
        
        async def work():
            results = []
            for i in range(0, len(message_ids), max_concurrent):
                batch = message_ids[i:i + max_concurrent]
                batch_results = await asyncio.gather(*[download_single(mid) for mid in batch])
                results.extend(batch_results)
            return results
        return self._run_async(work())

    def upload_chunks_parallel(self, chunk_paths, max_concurrent=3):
        target = self.channel_id
        async def upload_single(cp):
            return await self.client.send_document(target, document=cp, file_name=os.path.basename(cp))

        async def work():
            results = []
            for i in range(0, len(chunk_paths), max_concurrent):
                batch = chunk_paths[i:i + max_concurrent]
                batch_results = await asyncio.gather(*[upload_single(cp) for cp in batch])
                results.extend(batch_results)
            return results
        return self._run_async(work())


# Global bot instance
_bot_instance = None

def get_bot_client():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
