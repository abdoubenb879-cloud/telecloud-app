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
    global _loop, _loop_thread, _bot_instance
    
    # Quick check without lock
    if _loop_thread is not None and _loop_thread.is_alive() and _loop is not None:
        # Ensure the loop is accessible from this thread
        return _loop
    
    with _loop_lock:
        # Double-check after acquiring lock
        if _loop_thread is not None and _loop_thread.is_alive() and _loop is not None:
            return _loop
        
        # Reset state if thread died or never started
        print("[LOOP] Event loop thread died or not started, creating new one...")
        _loop_ready.clear()
        
        # CRITICAL: Reset the bot instance so it recreates with new loop
        # Reset both the global variable and the class singleton
        _bot_instance = None
        # We'll reset the class singleton after it's defined (see bottom of file)
        
        def run_loop():
            global _loop
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop_ready.set()
            print("[LOOP] New event loop started, running forever...")
            _loop.run_forever()
            
        _loop_thread = threading.Thread(target=run_loop, name="TeleCloudLoop", daemon=True)
        _loop_thread.start()
        
        # Wait for the loop to be assigned with a longer timeout
        if not _loop_ready.wait(timeout=30):
            raise RuntimeError("Failed to start event loop thread")
        
        print(f"[LOOP] Event loop thread started successfully: {_loop_thread}")
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
        
        self.bot_token = Config.BOT_TOKEN
        self.channel_id = Config.STORAGE_CHANNEL_ID
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required for Bot mode")
        if not self.channel_id:
            raise ValueError("STORAGE_CHANNEL_ID is required for Bot mode")
        
        # Create bot client synchronously
        async def create_bot():
            return Client(
                "telecloud_bot",
                api_id=self.api_id,
                api_hash=self.api_hash,
                bot_token=self.bot_token,
                in_memory=True,
                no_updates=True
            )
        
        self.client = asyncio.run(create_bot())
        self._connected = False
        self._initialized = True
        print("[BOT] BotClient initialized successfully")
    
    def _run_async(self, coro):
        """Run async operation synchronously using asyncio.run().
        
        This creates a fresh event loop for each operation, which is more
        reliable than maintaining a persistent daemon thread that can die.
        """
        print(f"[BOT._run_async] Running async operation with asyncio.run()...")
        try:
            # Use asyncio.run() which creates a fresh loop, runs to completion, then cleans up
            result = asyncio.run(coro)
            print(f"[BOT._run_async] Got result: {type(result)}")
            return result
        except Exception as e:
            print(f"[BOT._run_async] ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def connect(self):
        """Start the bot client (thread-safe)."""
        # Use lock to prevent multiple threads from triggering simultaneous auth
        with BotClient._lock:
            if not self._connected:
                async def work():
                    await self.client.start()
                self._run_async(work())
                self._connected = True
                print(f"[BOT] Connected to channel {self.channel_id}")
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
        """Upload multiple chunks in parallel to Telegram.
        
        Creates a fresh Pyrogram client for each upload operation to avoid
        event loop mismatch issues.
        """
        target = self.channel_id
        api_id = self.api_id
        api_hash = self.api_hash
        bot_token = self.bot_token
        
        print(f"[UPLOAD] Starting parallel upload to channel {target}, {len(chunk_paths)} chunks")
        
        async def do_upload():
            """Create client, connect, upload, disconnect - all in one async context."""
            print("[UPLOAD] Creating fresh Pyrogram client...")
            client = Client(
                "telecloud_upload",
                api_id=api_id,
                api_hash=api_hash,
                bot_token=bot_token,
                in_memory=True,
                no_updates=True
            )
            
            try:
                print("[UPLOAD] Starting client...")
                await client.start()
                print("[UPLOAD] Client connected!")
                
                async def upload_single(cp):
                    print(f"[UPLOAD] Uploading chunk: {cp}")
                    try:
                        result = await client.send_document(
                            target,
                            document=cp,
                            file_name=os.path.basename(cp)
                        )
                        print(f"[UPLOAD] Chunk uploaded successfully: {cp} -> msg_id={result.id if result else 'None'}")
                        return result
                    except Exception as e:
                        print(f"[UPLOAD] Chunk upload FAILED: {cp} -> {e}")
                        raise
                
                results = []
                for i in range(0, len(chunk_paths), max_concurrent):
                    batch = chunk_paths[i:i + max_concurrent]
                    print(f"[UPLOAD] Processing batch {i//max_concurrent + 1}: {batch}")
                    batch_results = await asyncio.gather(*[upload_single(cp) for cp in batch])
                    results.extend(batch_results)
                    print(f"[UPLOAD] Batch complete, got {len(batch_results)} results")
                
                print(f"[UPLOAD] All chunks done, returning {len(results)} results")
                return results
                
            finally:
                print("[UPLOAD] Stopping client...")
                await client.stop()
                print("[UPLOAD] Client stopped.")
        
        print(f"[UPLOAD] Running upload with asyncio.run()...")
        result = asyncio.run(do_upload())
        print(f"[UPLOAD] Upload completed, got result: {result}")
        return result


# Global bot instance (lazy initialization)
_bot_instance = None

def get_bot_client():
    """Get the global bot client instance."""
    global _bot_instance
    if _bot_instance is None:
        print("[BOT] Creating new BotClient instance...")
        _bot_instance = BotClient()
    return _bot_instance
