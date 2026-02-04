"""
TeleCloud Telegram Client - PERSISTENT POOL VERSION
Bots connect ONCE at startup and STAY connected.
All work is submitted to a dedicated async loop thread.
This is the most reliable way to use Pyrogram in multi-threaded apps.
"""
import asyncio
import os
import threading
import traceback
import time
from concurrent.futures import Future

# Apply Pyrogram patch for 64-bit channel IDs
import app.pyrogram_patch
from pyrogram import Client
from pyrogram.errors import FloodWait
from .config import Config


# ============================================================================
# DEDICATED EVENT LOOP THREAD
# ============================================================================

class AsyncLoopThread:
    """Runs a persistent event loop in a background thread."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="TeleCloudAsync", daemon=True)
        self.thread.start()
        
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        print("[LOOP] Async loop thread started")
        self.loop.run_forever()
        
    def run_coro(self, coro):
        """Submit a coroutine and return a Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

# Global loop thread
_async_thread = None

def get_async_thread():
    global _async_thread
    if _async_thread is None:
        _async_thread = AsyncLoopThread()
    return _async_thread


# ============================================================================
# PERSISTENT BOT CLIENT
# ============================================================================

class PersistentBotClient:
    """A wrapper for a Pyrogram Client that stays connected."""
    def __init__(self, name, token):
        self.name = name
        self.token = token
        self.client = Client(
            name,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=token,
            in_memory=True,
            no_updates=True,
            sleep_threshold=60,
            ipv6=False # Force IPv4 for stability on some clouds
        )
        self.is_connected = False
        self._async = get_async_thread()

    async def start(self):
        if not self.is_connected:
            try:
                print(f"[BOT-{self.name}] Connecting (IPv4 forced)...")
                await self.client.start()
                self.is_connected = True
                print(f"[BOT-{self.name}] Connection established!")
            except Exception as e:
                print(f"[BOT-{self.name}] CONNECTION FAILED: {e}")
                raise

    async def stop(self):
        if self.is_connected:
            await self.client.stop()
            self.is_connected = False

    def run_sync(self, coro, timeout=300):
        """Run an async method of THIS client in the async thread."""
        future = self._async.run_coro(coro)
        return future.result(timeout=timeout)


# ============================================================================
# GLOBAL BOT POOL
# ============================================================================

class BotPool:
    """Manages a pool of persistent, connected bots."""
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
            
        self.bots = []
        self._token_index = 0
        self._initialized = True
        
        # Load tokens
        tokens = Config.BOT_TOKENS
        if not tokens:
            tokens = []
            for key, val in os.environ.items():
                if key.startswith("BOT_TOKEN") and key != "BOT_TOKENS":
                    t = val.strip()
                    if t and t not in tokens:
                        tokens.append(t)
        
        for i, token in enumerate(tokens):
            name = f"worker_{i}_{threading.current_thread().name}"
            self.bots.append(PersistentBotClient(name, token))
            
        print(f"[POOL] Created pool with {len(self.bots)} bots")

    def connect(self):
        """Connect ALL bots in the pool. Call this at startup."""
        print(f"[POOL] Connecting {len(self.bots)} bots sequentially...")
        for bot in self.bots:
            try:
                get_async_thread().run_coro(bot.start()).result(timeout=60)
            except Exception as e:
                print(f"[POOL] Warning: Could not connect bot {bot.name}: {e}")
            
        print(f"[POOL] Pool ready! Connected bots: {[b.name for b in self.bots if b.is_connected]}")
        return self

    def _get_next_bot(self):
        with self._lock:
            bot = self.bots[self._token_index % len(self.bots)]
            self._token_index += 1
            return bot

    def upload_file(self, file_path, progress_callback=None):
        bot = self._get_next_bot()
        print(f"[POOL] Uploading using {bot.name}...")
        
        async def _upload():
            return await bot.client.send_document(
                chat_id=Config.STORAGE_CHANNEL_ID,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
            
        return bot.run_sync(_upload(), timeout=600)

    def download_file(self, message_id, output_path, progress_callback=None):
        bot = self._get_next_bot()
        async def _download():
            msg = await bot.client.get_messages(Config.STORAGE_CHANNEL_ID, message_id)
            return await bot.client.download_media(msg, file_name=output_path, progress=progress_callback)
        return bot.run_sync(_download(), timeout=600)

    def delete_message(self, message_id):
        bot = self._get_next_bot()
        async def _delete():
            await bot.client.delete_messages(Config.STORAGE_CHANNEL_ID, message_id)
        return bot.run_sync(_delete(), timeout=60)

    def download_media(self, message_id, in_memory=False):
        bot = self._get_next_bot()
        async def _download():
            msg = await bot.client.get_messages(Config.STORAGE_CHANNEL_ID, message_id)
            return await bot.client.download_media(msg, in_memory=in_memory)
        return bot.run_sync(_download(), timeout=600)

    def get_file_range(self, message_id, offset, limit):
        bot = self._get_next_bot()
        async def _stream():
            msg = await bot.client.get_messages(str(Config.STORAGE_CHANNEL_ID), message_id)
            chunk = b""
            async for data in bot.client.stream_media(msg, offset=offset, limit=limit):
                chunk += data
            return chunk
        return bot.run_sync(_stream(), timeout=120)

    def stop(self):
        async def _stop_all():
            tasks = [bot.stop() for bot in self.bots]
            await asyncio.gather(*tasks)
        get_async_thread().run_coro(_stop_all()).result()


# ============================================================================
# USER SESSION CLIENT (Dynamic)
# ============================================================================

class TelegramCloud:
    """Uses a dynamic client for user sessions."""
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        self.session_string = session_string
        self.client = None
        self._async = get_async_thread()

    def _create_client(self):
        if self.session_string:
            return Client(":memory:", api_id=self.api_id, api_hash=self.api_hash, session_string=self.session_string)
        else:
            return Client(Config.SESSION_NAME, api_id=self.api_id, api_hash=self.api_hash, workdir=Config.BASE_DIR)

    def connect(self):
        async def _do():
            self.client = self._create_client()
            await self.client.start()
            return await self.client.get_me()
        self._async.run_coro(_do()).result(timeout=60)
        return self

    def upload_file(self, file_path, progress_callback=None):
        async def _do():
            return await self.client.send_document(self.storage_chat, document=file_path, progress=progress_callback)
        return self._async.run_coro(_do()).result(timeout=600)

    def stop(self):
        if self.client:
            async def _do(): await self.client.stop()
            self._async.run_coro(_do()).result()


# ============================================================================
# GLOBAL ACCESS
# ============================================================================

def get_bot_client():
    return BotPool()
