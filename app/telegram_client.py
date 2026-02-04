"""
TeleCloud Telegram Client - DEDICATED LOOP THREAD VERSION
Uses a single persistent event loop thread for ALL async operations.
Background threads submit work to this loop using run_coroutine_threadsafe.
"""
import asyncio
import os
import threading
import traceback
import atexit

# Apply Pyrogram patch for 64-bit channel IDs
import app.pyrogram_patch
from pyrogram import Client
from pyrogram.errors import FloodWait
from .config import Config


# ============================================================================
# DEDICATED EVENT LOOP THREAD - Single loop for all async operations
# ============================================================================

class AsyncLoopThread:
    """
    Runs a dedicated event loop in a background thread.
    All async operations are submitted to this loop.
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
        
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._start_loop()
        self._initialized = True
    
    def _start_loop(self):
        """Start the event loop in a background thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            print("[LOOP] Event loop thread started")
            self._ready.set()
            try:
                self._loop.run_forever()
            finally:
                self._loop.close()
                print("[LOOP] Event loop thread stopped")
        
        self._thread = threading.Thread(target=run_loop, name="TeleCloudAsyncLoop", daemon=True)
        self._thread.start()
        
        # Wait for loop to be ready
        self._ready.wait(timeout=10)
        if not self._ready.is_set():
            raise RuntimeError("Event loop thread failed to start")
        print("[LOOP] Event loop ready")
    
    def run(self, coro, timeout=120):
        """
        Run a coroutine on the event loop thread and wait for result.
        Safe to call from any thread.
        """
        if self._loop is None or not self._thread.is_alive():
            print("[LOOP] Loop died, restarting...")
            self._ready.clear()
            self._start_loop()
        
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            print(f"[LOOP] Error running coroutine: {e}")
            traceback.print_exc()
            raise
    
    def stop(self):
        """Stop the event loop."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# Global loop instance
_loop_thread = None

def get_loop():
    """Get the global async loop thread."""
    global _loop_thread
    if _loop_thread is None:
        _loop_thread = AsyncLoopThread()
    return _loop_thread


# ============================================================================
# TELEGRAM UPLOADER - Uses the dedicated loop thread
# ============================================================================

class TelegramUploader:
    """
    Simple Telegram uploader that uses the shared event loop thread.
    Thread-safe - can be called from any thread.
    """
    
    def __init__(self, bot_token, api_id=None, api_hash=None, channel_id=None):
        self.bot_token = bot_token
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.channel_id = channel_id or Config.STORAGE_CHANNEL_ID
        self._name = f"uploader_{id(self)}"
        self._loop = get_loop()
    
    def _create_client(self):
        """Create a fresh Pyrogram client."""
        return Client(
            self._name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            bot_token=self.bot_token,
            in_memory=True,
            no_updates=True
        )
    
    def test_connection(self):
        """Test that the bot can connect."""
        print("[UPLOADER] Testing connection...")
        
        async def _test():
            print("[UPLOADER] Creating client...")
            client = self._create_client()
            try:
                print("[UPLOADER] Starting client...")
                await client.start()
                print("[UPLOADER] Client started!")
                me = await client.get_me()
                print(f"[UPLOADER] Connected as @{me.username}")
                return me
            except Exception as e:
                print(f"[UPLOADER] Connection failed: {e}")
                traceback.print_exc()
                raise
            finally:
                try:
                    print("[UPLOADER] Stopping client...")
                    await client.stop()
                    print("[UPLOADER] Client stopped.")
                except Exception as se:
                    print(f"[UPLOADER] Stop error: {se}")
        
        return self._loop.run(_test())
    
    def upload_file(self, file_path, progress_callback=None):
        """Upload a file to the channel."""
        print(f"[UPLOADER] Uploading: {file_path}")
        print(f"[UPLOADER] To channel: {self.channel_id}")
        
        async def _upload():
            print("[UPLOADER] Creating client for upload...")
            client = self._create_client()
            try:
                print("[UPLOADER] Starting client for upload...")
                await client.start()
                print("[UPLOADER] Client started, sending document...")
                
                result = await client.send_document(
                    chat_id=self.channel_id,
                    document=file_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback
                )
                
                print(f"[UPLOADER] Upload SUCCESS! Message ID: {result.id}")
                return result
            
            except FloodWait as e:
                print(f"[UPLOADER] FloodWait: {e.value} seconds")
                await asyncio.sleep(e.value)
                result = await client.send_document(
                    chat_id=self.channel_id,
                    document=file_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback
                )
                print(f"[UPLOADER] Retry SUCCESS! Message ID: {result.id}")
                return result
            
            except Exception as e:
                print(f"[UPLOADER] Upload FAILED: {e}")
                traceback.print_exc()
                raise
            
            finally:
                try:
                    print("[UPLOADER] Stopping client after upload...")
                    await client.stop()
                    print("[UPLOADER] Client stopped after upload.")
                except Exception as se:
                    print(f"[UPLOADER] Stop error: {se}")
        
        return self._loop.run(_upload(), timeout=300)  # 5 min timeout for uploads
    
    def download_file(self, message_id, output_path, progress_callback=None):
        """Download a file from the channel."""
        print(f"[UPLOADER] Downloading message {message_id}")
        
        async def _download():
            client = self._create_client()
            try:
                await client.start()
                msg = await client.get_messages(self.channel_id, message_id)
                if not msg or not msg.document:
                    raise Exception("File not found")
                result = await client.download_media(
                    msg,
                    file_name=output_path,
                    progress=progress_callback
                )
                print(f"[UPLOADER] Download complete: {result}")
                return result
            finally:
                await client.stop()
        
        return self._loop.run(_download(), timeout=300)
    
    def delete_message(self, message_id):
        """Delete a message from the channel."""
        print(f"[UPLOADER] Deleting message {message_id}")
        
        async def _delete():
            client = self._create_client()
            try:
                await client.start()
                await client.delete_messages(self.channel_id, message_id)
                print("[UPLOADER] Message deleted")
            finally:
                await client.stop()
        
        return self._loop.run(_delete())
    
    def download_media(self, message_id, in_memory=False):
        """Download media from the channel."""
        async def _download():
            client = self._create_client()
            try:
                await client.start()
                msg = await client.get_messages(self.channel_id, message_id)
                if not msg or not msg.document:
                    return None
                return await client.download_media(msg, in_memory=in_memory)
            finally:
                await client.stop()
        
        return self._loop.run(_download(), timeout=300)
    
    def get_file_range(self, message_id, offset, limit):
        """Download a specific byte range."""
        async def _stream():
            client = self._create_client()
            try:
                await client.start()
                msg = await client.get_messages(str(self.channel_id), message_id)
                if not msg or not msg.document:
                    return None
                chunk = b""
                async for data in client.stream_media(msg, offset=offset, limit=limit):
                    chunk += data
                return chunk
            finally:
                await client.stop()
        
        return self._loop.run(_stream())


# ============================================================================
# BOT CLIENT - Token rotation and management
# ============================================================================

class BotClient:
    """Manages multiple bot tokens with round-robin."""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        self.channel_id = Config.STORAGE_CHANNEL_ID
        self.bot_tokens = Config.BOT_TOKENS
        
        if not self.bot_tokens:
            print("[BOT] Scanning environment for tokens...")
            self.bot_tokens = []
            for key, val in os.environ.items():
                if key.startswith("BOT_TOKEN") and key != "BOT_TOKENS":
                    token = val.strip()
                    if token and token not in self.bot_tokens:
                        self.bot_tokens.append(token)
                        print(f"[BOT] Found token from {key}")
        
        if not self.bot_tokens:
            raise ValueError("No BOT_TOKENS provided!")
        
        self._token_index = 0
        self._initialized = True
        print(f"[BOT] Initialized with {len(self.bot_tokens)} bot tokens")
    
    def _get_next_token(self):
        token = self.bot_tokens[self._token_index % len(self.bot_tokens)]
        self._token_index += 1
        return token
    
    def _create_uploader(self):
        return TelegramUploader(
            bot_token=self._get_next_token(),
            api_id=self.api_id,
            api_hash=self.api_hash,
            channel_id=self.channel_id
        )
    
    def connect(self):
        """Test connection."""
        uploader = self._create_uploader()
        uploader.test_connection()
        print("[BOT] Connection test successful!")
        return self
    
    def upload_file(self, file_path, progress_callback=None):
        uploader = self._create_uploader()
        return uploader.upload_file(file_path, progress_callback)
    
    def upload_chunks_parallel(self, chunk_paths, max_concurrent=3):
        """Upload multiple chunks."""
        print(f"[BOT] Uploading {len(chunk_paths)} chunks...")
        results = []
        for i, chunk_path in enumerate(chunk_paths):
            print(f"[BOT] Chunk {i+1}/{len(chunk_paths)}")
            uploader = self._create_uploader()
            result = uploader.upload_file(chunk_path)
            results.append(result)
        print(f"[BOT] All {len(results)} chunks uploaded!")
        return results
    
    def download_file(self, message_id, output_path, progress_callback=None):
        uploader = self._create_uploader()
        return uploader.download_file(message_id, output_path, progress_callback)
    
    def delete_message(self, message_id):
        uploader = self._create_uploader()
        return uploader.delete_message(message_id)
    
    def download_media(self, message_id, in_memory=False):
        uploader = self._create_uploader()
        return uploader.download_media(message_id, in_memory)
    
    def get_file_range(self, message_id, offset, limit):
        uploader = self._create_uploader()
        return uploader.get_file_range(message_id, offset, limit)
    
    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        results = []
        for msg_id in message_ids:
            uploader = self._create_uploader()
            result = uploader.download_media(msg_id)
            results.append(result)
        return results
    
    def stop(self):
        pass


# ============================================================================
# TELEGRAM CLOUD - User session client
# ============================================================================

class TelegramCloud:
    """User session client."""
    
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        self.session_string = session_string
        self._connected = False
        self._resolved_chat_id = None
        self.storage_chat_title = "My Cloud Storage"
        self._loop = get_loop()
    
    def _create_client(self):
        if self.session_string:
            return Client(
                "telecloud_user",
                api_id=self.api_id,
                api_hash=self.api_hash,
                session_string=self.session_string,
                in_memory=True,
                no_updates=True
            )
        else:
            return Client(
                Config.SESSION_NAME,
                api_id=self.api_id,
                api_hash=self.api_hash,
                workdir=Config.BASE_DIR,
                no_updates=True
            )
    
    def connect(self):
        if not self._connected:
            async def _connect():
                client = self._create_client()
                await client.start()
                me = await client.get_me()
                await client.stop()
                return me
            
            self._loop.run(_connect())
            self._connected = True
            self._resolve_chat()
        return self
    
    def _resolve_chat(self):
        try:
            async def _resolve():
                client = self._create_client()
                await client.start()
                chat = await client.get_chat(self.storage_chat)
                await client.stop()
                return chat
            
            chat = self._loop.run(_resolve())
            self._resolved_chat_id = chat.id
            self.storage_chat_title = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Private Chat')
        except:
            self._resolved_chat_id = None
            self.storage_chat_title = "Saved Messages"
    
    def upload_file(self, file_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _upload():
            client = self._create_client()
            await client.start()
            result = await client.send_document(
                target,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
            await client.stop()
            return result
        
        return self._loop.run(_upload(), timeout=300)
    
    def download_file(self, message_id, output_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _download():
            client = self._create_client()
            await client.start()
            message = await client.get_messages(target, message_id)
            if not message or not message.document:
                await client.stop()
                raise Exception("File not found.")
            result = await client.download_media(message, file_name=output_path, progress=progress_callback)
            await client.stop()
            return result
        
        return self._loop.run(_download(), timeout=300)
    
    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _delete():
            client = self._create_client()
            await client.start()
            await client.delete_messages(target, message_id)
            await client.stop()
        
        self._loop.run(_delete())
    
    def download_media(self, message_id, in_memory=False):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _download():
            client = self._create_client()
            await client.start()
            msg = await client.get_messages(target, message_id)
            if not msg or not msg.document:
                await client.stop()
                return None
            result = await client.download_media(msg, in_memory=in_memory)
            await client.stop()
            return result
        
        return self._loop.run(_download(), timeout=300)
    
    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        loop = get_loop()
        
        async def _send():
            temp_client = Client(":memory:", api_id=api_id, api_hash=api_hash, in_memory=True)
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
        
        return loop.run(_send())
    
    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        loop = get_loop()
        
        async def _complete():
            await temp_client.sign_in(phone, code_hash, code)
            session_str = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            return session_str, me.id
        
        return loop.run(_complete())
    
    def stop(self):
        self._connected = False


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_bot_instance = None

def get_bot_client():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance


# Initialize the loop thread early
def _init():
    try:
        get_loop()
        print("[INIT] Async loop thread initialized")
    except Exception as e:
        print(f"[INIT] Failed to initialize loop thread: {e}")

_init()
