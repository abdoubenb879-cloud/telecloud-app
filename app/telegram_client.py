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
                    
                    # Add a keepalive task to prevent the loop from having nothing to do
                    async def keepalive():
                        while True:
                            await asyncio.sleep(60)  # Heartbeat every 60 seconds
                    
                    _loop.create_task(keepalive())
                    _loop_ready.set()
                    print(f"[LOOP] Loop {_loop} running in thread {threading.current_thread().name}")
                    _loop.run_forever()
                except Exception as e:
                    print(f"[LOOP] Loop crashed: {e}")
                    import traceback
                    traceback.print_exc()

            # CRITICAL: daemon=False keeps thread alive even when main thread is idle
            _loop_thread = threading.Thread(target=run_loop, name="TeleCloudLoop", daemon=False)
            _loop_thread.start()
            
            # Wait for startup
            if not _loop_ready.wait(timeout=30):
                raise RuntimeError("Failed to start event loop thread")
        
        return _loop

class TelegramCloud:
    """Dynamic Telegram client meant to be instantiated per user session."""
    
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        ensure_loop_running() 
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        
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
# BOT CLIENT - Centralized storage using a scaled WORKER POOL
# ============================================================================

class BotClient:
    """
    Singleton Bot client manager.
    Manages a POOL of worker bots for high-concurrency uploads.
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
            
        self.channel_id = Config.STORAGE_CHANNEL_ID
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        # Try Config first
        self.bot_tokens = Config.BOT_TOKENS
        
        # Fallback: aggressive reload from environment if Config is empty
        if not self.bot_tokens:
            print("[BOT-INIT] Config.BOT_TOKENS is empty! Attempting manual reload...")
            raw_tokens = os.getenv("BOT_TOKENS", "")
            fallback_token = os.getenv("BOT_TOKEN", "")
            
            print(f"[BOT-INIT] Raw BOT_TOKENS len: {len(raw_tokens)}")
            print(f"[BOT-INIT] Raw BOT_TOKEN len: {len(fallback_token)}")
            
            self.bot_tokens = [t.strip() for t in raw_tokens.split(",") if t.strip()]
            if not self.bot_tokens and fallback_token:
                self.bot_tokens = [fallback_token]
                
        if not self.bot_tokens:
            print("[BOT-CRITICAL] Still no tokens found after fallback!")
            raise ValueError("No BOT_TOKENS provided! Cannot start.")
        if not self.channel_id:
            raise ValueError("STORAGE_CHANNEL_ID is required.")
        
        self.clients = [] # List of Pyrogram Clients
        self._loop_id = None
        self._current_worker_index = 0
        
        self._create_clients_on_loop()
        self._initialized = True
        print(f"[BOT-POOL] Initialized with {len(self.clients)} worker bots.")

    def _create_clients_on_loop(self):
        """Creates the worker pool on the current loop."""
        ensure_loop_running()
        
        print(f"[BOT-POOL] Creating {len(self.bot_tokens)} clients on loop...")
        self.clients = []
        
        async def create_all():
            created = []
            for i, token in enumerate(self.bot_tokens):
                try:
                    # Unique session name for each worker
                    name = f"worker_{i}" 
                    c = Client(name, api_id=self.api_id, api_hash=self.api_hash, bot_token=token, in_memory=True, no_updates=True)
                    created.append(c)
                except Exception as e:
                    print(f"[BOT-POOL] Failed to create worker {i}: {e}")
            return created
        
        future = asyncio.run_coroutine_threadsafe(create_all(), _loop)
        self.clients = future.result(timeout=60)
        self._loop_id = id(_loop)

    def _get_worker(self):
        """Round-robin selection of a worker."""
        if not self.clients:
            self._ensure_health() # Panic recovery
            return None 
            
        # Round Robin
        client = self.clients[self._current_worker_index % len(self.clients)]
        self._current_worker_index += 1
        return client

    def _ensure_health(self):
        """Checks if loop is alive and matches our client pool."""
        global _loop, _loop_thread
        
        is_dead = _loop_thread is None or not _loop_thread.is_alive()
        loop_changed = id(_loop) != self._loop_id if _loop else True
        
        if is_dead or loop_changed:
            print(f"[BOT-FIX] Pool Health Check Failed (Dead={is_dead}, Changed={loop_changed}). Rebooting Pool...")
            ensure_loop_running()
            if id(_loop) != self._loop_id:
                print("[BOT-FIX] Recreating implementation pool...")
                self._create_clients_on_loop()
                print("[BOT-FIX] Reconnecting all workers...")
                self.connect()

    def _run_async(self, coro):
        """Run async operation with pool recovery."""
        self._ensure_health()
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        try:
            return future.result(timeout=300) # 5m timeout
        except Exception as e:
            print(f"[BOT-ERROR] Async task failed: {e}")
            raise

    def connect(self):
        with BotClient._lock:
            # Connect ALL workers
            async def connect_all():
                tasks = []
                for i, c in enumerate(self.clients):
                   if not c.is_connected:
                       tasks.append(self._safe_start(c, i))
                if tasks:
                    await asyncio.gather(*tasks)
            
            self._run_async(connect_all())
            print(f"[BOT-POOL] All workers connected to channel {self.channel_id}")
        return self
    
    async def _safe_start(self, client, index):
        try:
            await client.start()
        except Exception as e:
             if "FLOOD_WAIT" in str(e):
                import re
                match = re.search(r'wait of (\d+) seconds', str(e))
                wait = int(match.group(1)) if match else 60
                print(f"[WORKER-{index}] 🛑 RATELIMIT: Waiting {wait}s")
                await asyncio.sleep(wait)
                await client.start()
             else:
                 print(f"[WORKER-{index}] Failed to start: {e}")

    def upload_file(self, file_path, progress_callback=None):
        client = self._get_worker()
        if not client: raise RuntimeError("No workers available")
        async def work():
            return await client.send_document(self.channel_id, document=file_path, file_name=os.path.basename(file_path), progress=progress_callback)
        return self._run_async(work())
    
    def upload_chunks_parallel(self, chunk_paths, max_concurrent=3):
        target = self.channel_id
        
        # We can now use MULTIPLE workers for a single file upload if we want!
        # But simpler: Each chunk gets assigned a worker round-robin.
        
        async def upload_single(cp, worker):
            return await worker.send_document(target, document=cp, file_name=os.path.basename(cp))

        async def work():
            tasks = []
            for cp in chunk_paths:
                worker = self._get_worker() # Load balance chunks across bots!
                if not worker: continue
                tasks.append(upload_single(cp, worker))
            
            # Limit concurrency per batch to avoid blowing up memory
            # If 10 bots, we can do 10-20 parallel easily.
            results = []
            batch_size = 5
            for i in range(0, len(tasks), batch_size):
                 batch = tasks[i:i+batch_size]
                 batch_errors = await asyncio.gather(*batch, return_exceptions=True)
                 for res in batch_errors:
                     if isinstance(res, Exception): raise res
                     results.append(res)
            return results
            
        return self._run_async(work())

    # ... (Keep download/delete/etc methods similar, using self._get_worker()) ...
    def download_file(self, message_id, output_path, progress_callback=None):
        client = self._get_worker()
        if not client: raise RuntimeError("No workers available")
        async def work():
            msg = await client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document: raise Exception("File not found")
            return await client.download_media(msg, file_name=output_path, progress=progress_callback)
        return self._run_async(work())
    
    def delete_message(self, message_id):
        client = self._get_worker()
        if not client: return
        async def work(): await client.delete_messages(self.channel_id, message_id)
        self._run_async(work())
    
    def download_media(self, message_id, in_memory=False):
        client = self._get_worker()
        if not client: return None
        async def work():
            msg = await client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document: return None
            return await client.download_media(msg, in_memory=in_memory)
        return self._run_async(work())

    def get_file_range(self, message_id, offset, limit):
        client = self._get_worker()
        if not client: return None
        async def work():
            msg = await client.get_messages(str(self.channel_id), message_id)
            if not msg or not msg.document: return None
            chunk = b""
            async for data in client.stream_media(msg, offset=offset, limit=limit):
                chunk += data
            return chunk
        return self._run_async(work())

    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        async def download_single(msg_id, worker):
            msg = await worker.get_messages(self.channel_id, msg_id)
            if not msg or not msg.document: return None
            return await worker.download_media(msg, in_memory=False)
        
        async def work():
            tasks = []
            for mid in message_ids:
                worker = self._get_worker() # Spread download load too
                if not worker: continue
                tasks.append(download_single(mid, worker))
            
            # Use gather
            return await asyncio.gather(*tasks)
            
        return self._run_async(work())
    
    def stop(self):
        # Stop all workers
        pass

# Global bot instance
_bot_instance = None

def get_bot_client():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
