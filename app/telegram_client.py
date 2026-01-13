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
    
    # Quick check without lock
    if _loop_thread is not None and _loop_thread.is_alive() and _loop is not None:
        # Ensure the loop is accessible from this thread
        return _loop
    
    with _loop_lock:
        # Double-check after acquiring lock
        if _loop_thread is not None and _loop_thread.is_alive() and _loop is not None:
            return _loop
        
        # Reset state if thread died or never started
        _loop_ready.clear()
        
        def run_loop():
            global _loop
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop_ready.set()
            _loop.run_forever()
            
        _loop_thread = threading.Thread(target=run_loop, name="TeleCloudLoop", daemon=True)
        _loop_thread.start()
        
        # Wait for the loop to be assigned with a longer timeout
        if not _loop_ready.wait(timeout=30):
            raise RuntimeError("Failed to start event loop thread")
        
        return _loop

class TelegramCloud:
    """Dynamic Telegram client meant to be instantiated per user session."""
    
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        # Ensure the background thread is running in this process
        ensure_loop_running()
        
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        
        if session_string:
            async def create_cloud_client():
                return Client(
                    "telecloud_client", # Internal name (not a file)
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
        """Helper to run a coroutine or coroutine function in the background loop thread."""
        print(f"[ASYNC] Submitting work to loop {_loop}...")
        if asyncio.iscoroutine(coro_or_func):
            coro = coro_or_func
        else:
            coro = coro_or_func()
            
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        print(f"[ASYNC] Future created: {future}. Waiting for result...")
        try:
            res = future.result(timeout=6000)
            print(f"[ASYNC] Result received: {type(res)}")
            return res
        except Exception as e:
            print(f"[ASYNC] ERROR waiting for future: {e}")
            raise

    def connect(self):
        """Starts the Pyrogram client and resolves the storage chat."""
        if not self._connected:
            async def work():
                await self.client.start()
            self._run_async(work)
            self._connected = True
            self._resolve_chat()
        return self

    def stop(self):
        """Stops the client."""
        if self._connected:
            async def work():
                await self.client.stop()
            self._run_async(work)
            self._connected = False

    def _resolve_chat(self):
        """Finds the ID of the storage channel."""
        try:
            async def work():
                return await self.client.get_chat(self.storage_chat)
            chat = self._run_async(work)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Private Chat')
        except Exception:
            async def work_me():
                return await self.client.get_chat("me")
            chat = self._run_async(work_me)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = "Saved Messages"

    def upload_file(self, file_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        async def work():
            return await self.client.send_document(
                target,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
        return self._run_async(work)

    def download_file(self, message_id, output_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        
        async def get_msg():
            return await self.client.get_messages(target, message_id)
        
        message = self._run_async(get_msg)
        if not message or not message.document:
            raise Exception("File not found on Telegram.")
            
        async def dl():
            return await self.client.download_media(message, file_name=output_path, progress=progress_callback)
            
        return self._run_async(dl)

    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        async def work():
            await self.client.delete_messages(target, message_id)
        self._run_async(work)

    def download_media(self, message_id, in_memory=False):
        """Downloads media from a message ID. Returns path or bytes."""
        target = self._resolved_chat_id or self.storage_chat
        async def work():
            msg = await self.client.get_messages(target, message_id)
            if not msg or not msg.document:
                return None
            return await self.client.download_media(msg, in_memory=in_memory)
        return self._run_async(work)

    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        """Starts auth flow and returns code_hash."""
        loop = ensure_loop_running()
        
        async def work():
            # Create client INSIDE the async context to avoid event loop issues
            temp_client = Client(
                ":memory:", 
                api_id=api_id, 
                api_hash=api_hash,
                in_memory=True
            )
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
            
        return asyncio.run_coroutine_threadsafe(work(), _loop).result(timeout=60)

    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        """Finishes auth and returns session string."""
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
    Singleton Bot client for centralized file storage.
    All users share this single bot instance for uploads/downloads.
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
            
        ensure_loop_running()
        
        self.bot_token = Config.BOT_TOKEN
        self.channel_id = Config.STORAGE_CHANNEL_ID
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required for Bot mode")
        if not self.channel_id:
            raise ValueError("STORAGE_CHANNEL_ID is required for Bot mode")
        
        # Create bot client
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
        self._initialized = True
        print("[BOT] BotClient initialized successfully")
    
    # Class-level cooldown tracking (shared across all instances)
    _flood_wait_until = 0  # Unix timestamp when FloodWait expires
    _flood_wait_duration = 0  # Original duration for logging
    
    def _run_async(self, coro, timeout=120):
        """Run async operation in the background loop with timeout."""
        import sys
        global _loop, _loop_thread
        
        # CRITICAL: After gunicorn forks, the background thread doesn't exist!
        # We must ensure the loop is running in THIS process
        if _loop_thread is None or not _loop_thread.is_alive():
            print("[BOT] Background thread not alive, recreating event loop...", flush=True)
            ensure_loop_running()
            
            # CRITICAL FIX: Also reset client state after fork!
            # The old client was connected to the dead loop
            if self._connected:
                print("[BOT] Resetting client connection state after fork...", flush=True)
                self._connected = False
                # Recreate the Pyrogram client instance for the new loop
                self.client = Client(
                    "telecloud_bot",
                    api_id=Config.API_ID,
                    api_hash=Config.API_HASH,
                    bot_token=Config.BOT_TOKEN,
                    in_memory=True,
                    no_updates=True
                )
                print("[BOT] New client instance created, will reconnect on demand", flush=True)

        
        # Check if loop is actually running
        if _loop is None:
            print("[BOT] ERROR: Background loop is None!", flush=True)
            raise RuntimeError("Background event loop not initialized")
        
        if not _loop.is_running():
            print("[BOT] ERROR: Background loop is not running!", flush=True)
            # Try to recreate it
            print("[BOT] Attempting to recreate event loop...", flush=True)
            ensure_loop_running()
        
        print(f"[BOT] Submitting coroutine to loop (loop running: {_loop.is_running()}, thread alive: {_loop_thread.is_alive() if _loop_thread else False})", flush=True)
        
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        
        print(f"[BOT] Future created, waiting up to {timeout}s for result...", flush=True)
        sys.stdout.flush()
        
        try:
            result = future.result(timeout=timeout)
            print(f"[BOT] Future completed successfully", flush=True)
            return result
        except TimeoutError:
            print(f"[BOT] TIMEOUT: Coroutine did not complete in {timeout}s", flush=True)
            raise
        except Exception as e:
            print(f"[BOT] Future raised exception: {type(e).__name__}: {e}", flush=True)
            raise
    
    @classmethod
    def get_cooldown_status(cls):
        """Check if we're in a FloodWait cooldown period."""
        import time as time_module
        now = time_module.time()
        if now < cls._flood_wait_until:
            remaining = int(cls._flood_wait_until - now)
            return True, remaining
        return False, 0
    
    @classmethod
    def clear_cooldown(cls):
        """Manually clear the cooldown (use with caution)."""
        cls._flood_wait_until = 0
        cls._flood_wait_duration = 0
        print("[BOT] FloodWait cooldown manually cleared")
    
    def connect(self, max_retries=1):
        """Start the bot client (thread-safe with FloodWait cooldown)."""
        from pyrogram.errors import FloodWait
        import time as time_module
        
        # CRITICAL FIX: Check if already connected FIRST, before cooldown check
        # This prevents false failures when bot connected successfully at startup
        if self._connected:
            return self
        
        # Check if we're in cooldown - don't even try to connect
        in_cooldown, remaining = BotClient.get_cooldown_status()
        if in_cooldown:
            print(f"[BOT] In FloodWait cooldown. {remaining}s remaining. Skipping connection attempt.")
            raise Exception(f"FloodWait cooldown active. Wait {remaining} seconds before retry.")
        
        # Use lock to prevent multiple threads from triggering simultaneous auth
        with BotClient._lock:
            # Double-check connected status inside lock (another thread might have connected)
            if self._connected:
                return self
            
            # Double-check cooldown inside lock
            in_cooldown, remaining = BotClient.get_cooldown_status()
            if in_cooldown:
                raise Exception(f"FloodWait cooldown active. Wait {remaining} seconds before retry.")
                
            for attempt in range(max_retries):
                try:
                    async def work():
                        await self.client.start()
                    
                    # Use 60 second timeout to prevent hanging forever
                    self._run_async(work(), timeout=60)
                    self._connected = True
                    # Clear cooldown on successful connection
                    BotClient._flood_wait_until = 0
                    print(f"[BOT] Connected to channel {self.channel_id}")
                    return self
                    
                except FloodWait as fw:
                    wait_time = fw.value if hasattr(fw, 'value') else 300
                    # Set cooldown to prevent future attempts
                    BotClient._flood_wait_until = time_module.time() + wait_time
                    BotClient._flood_wait_duration = wait_time
                    print(f"[BOT] FloodWait: {wait_time}s. Cooldown set until {BotClient._flood_wait_until}")
                    print(f"[BOT] NO MORE CONNECTION ATTEMPTS will be made for {wait_time} seconds")
                    raise Exception(f"Telegram FloodWait: Must wait {wait_time} seconds")
                        
                except Exception as e:
                    print(f"[BOT] Connection attempt {attempt+1} failed: {e}")
                    if attempt < max_retries - 1:
                        time_module.sleep(5)
                    else:
                        raise
        
        return self
    
    def stop(self):
        """Stop the bot client."""
        if self._connected:
            async def work():
                await self.client.stop()
            self._run_async(work())
            self._connected = False
    
    def upload_file(self, file_path, progress_callback=None):
        """Upload a file to the storage channel."""
        async def work():
            return await self.client.send_document(
                self.channel_id,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
        return self._run_async(work())
    
    def download_file(self, message_id, output_path, progress_callback=None):
        """Download a file from the storage channel."""
        async def work():
            msg = await self.client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document:
                raise Exception("File not found on Telegram")
            return await self.client.download_media(msg, file_name=output_path, progress=progress_callback)
        return self._run_async(work())
    
    def delete_message(self, message_id):
        """Delete a message from the storage channel."""
        async def work():
            await self.client.delete_messages(self.channel_id, message_id)
        self._run_async(work())
    
    def download_media(self, message_id, in_memory=False):
        """Download media, optionally in-memory."""
        async def work():
            msg = await self.client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document:
                return None
            return await self.client.download_media(msg, in_memory=in_memory)
        return self._run_async(work())

    def get_file_range(self, message_id, offset, limit):
        """Get a specific range of bytes from a file (for streaming)."""
        async def work():
            msg = await self.client.get_messages(str(self.channel_id), message_id)
            if not msg or not msg.document:
                return None
            
            chunk = b""
            # stream_media yields chunks. We collect them up to the limit.
            async for data in self.client.stream_media(msg, offset=offset, limit=limit):
                chunk += data
            return chunk
            
        return self._run_async(work())

    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        """Download multiple chunks in parallel for faster downloads."""
        async def download_single(msg_id):
            msg = await self.client.get_messages(self.channel_id, msg_id)
            if not msg or not msg.document:
                return None
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
        """Upload multiple chunks in parallel to Telegram."""
        target = self.channel_id
        print(f"[BOT] Starting parallel upload of {len(chunk_paths)} chunks to channel {target}", flush=True)
        print(f"[BOT] Chunk paths: {chunk_paths}", flush=True)
        
        async def upload_single(cp, idx):
            print(f"[BOT] >>> Entering upload_single for chunk {idx+1}", flush=True)
            print(f"[BOT] Uploading chunk {idx+1}/{len(chunk_paths)}: {os.path.basename(cp)}", flush=True)
            try:
                print(f"[BOT] Calling send_document for chunk {idx+1}...", flush=True)
                result = await self.client.send_document(
                    target,
                    document=cp,
                    file_name=os.path.basename(cp)
                )
                print(f"[BOT] Chunk {idx+1} uploaded successfully, msg_id: {result.id}", flush=True)
                return result
            except Exception as e:
                print(f"[BOT] Chunk {idx+1} upload FAILED: {type(e).__name__}: {e}", flush=True)
                import traceback
                traceback.print_exc()
                raise
        
        async def work():
            print(f"[BOT] >>> Entering work() coroutine", flush=True)
            results = []
            for i in range(0, len(chunk_paths), max_concurrent):
                batch = chunk_paths[i:i + max_concurrent]
                batch_indices = list(range(i, min(i + max_concurrent, len(chunk_paths))))
                print(f"[BOT] Processing batch: chunks {batch_indices}", flush=True)
                try:
                    print(f"[BOT] About to gather uploads for batch...", flush=True)
                    batch_results = await asyncio.gather(*[upload_single(cp, idx) for idx, cp in zip(batch_indices, batch)])
                    print(f"[BOT] Batch completed with {len(batch_results)} results", flush=True)
                    results.extend(batch_results)
                except Exception as e:
                    print(f"[BOT] Batch upload FAILED: {type(e).__name__}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    raise
            print(f"[BOT] All batches complete, returning {len(results)} results", flush=True)
            return results
        
        # Use 10 minute timeout for large file uploads
        print(f"[BOT] Calling _run_async with 600s timeout...", flush=True)
        try:
            result = self._run_async(work(), timeout=600)
            print(f"[BOT] _run_async returned successfully")
            return result
        except Exception as e:
            print(f"[BOT] _run_async FAILED: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise


# Global bot instance (lazy initialization)
_bot_instance = None

def get_bot_client():
    """Get the global bot client instance."""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
