"""
TeleCloud Telegram Client - SIMPLIFIED VERSION
Uses asyncio.run() per-operation instead of persistent background threads.
This is more reliable in serverless/worker environments like Render.
"""
import asyncio
import os
import threading

# Apply patch before importing Client
import app.pyrogram_patch
from pyrogram import Client
from pyrogram.errors import FloodWait
from .config import Config


# ============================================================================
# SIMPLE BOT CLIENT - No persistent threads, uses asyncio.run() per call
# ============================================================================

class BotClient:
    """
    Simplified Bot client that creates fresh connections per operation.
    No background threads, no persistent event loops.
    Works reliably in gunicorn and serverless environments.
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
        self.bot_tokens = Config.BOT_TOKENS
        
        # Fallback: scan environment for BOT_TOKEN* variables
        if not self.bot_tokens:
            print("[BOT-INIT] Config.BOT_TOKENS is empty! Scanning environment...")
            self.bot_tokens = []
            for key, val in os.environ.items():
                if key.startswith("BOT_TOKEN") and key != "BOT_TOKENS" and val.strip():
                    if val.strip() not in self.bot_tokens:
                        self.bot_tokens.append(val.strip())
                        print(f"[BOT-INIT] Found token from {key}")
                        
        if not self.bot_tokens:
            raise ValueError("No BOT_TOKENS provided! Cannot start.")
        if not self.channel_id:
            raise ValueError("STORAGE_CHANNEL_ID is required.")
        
        self._current_worker_index = 0
        self._initialized = True
        print(f"[BOT-POOL] Initialized with {len(self.bot_tokens)} worker bot tokens.")

    def _get_next_token(self):
        """Round-robin token selection."""
        token = self.bot_tokens[self._current_worker_index % len(self.bot_tokens)]
        self._current_worker_index += 1
        return token

    def _run_with_client(self, async_func):
        """
        Creates a fresh client, runs the async function, then closes.
        Uses asyncio.run() which is safe in any thread context.
        """
        token = self._get_next_token()
        worker_name = f"worker_{self._current_worker_index}"
        
        async def wrapper():
            client = Client(
                worker_name,
                api_id=self.api_id,
                api_hash=self.api_hash,
                bot_token=token,
                in_memory=True,
                no_updates=True
            )
            try:
                await client.start()
                print(f"[BOT] Worker connected, executing operation...")
                result = await async_func(client)
                print(f"[BOT] Operation completed successfully!")
                return result
            except FloodWait as e:
                print(f"[BOT] FloodWait: sleeping {e.value} seconds...")
                await asyncio.sleep(e.value)
                return await async_func(client)
            except Exception as e:
                print(f"[BOT] Error: {e}")
                raise
            finally:
                try:
                    await client.stop()
                except:
                    pass
        
        # asyncio.run() creates a new event loop, runs the coroutine, then closes it
        # This is safe and works in any thread/process context
        return asyncio.run(wrapper())

    def connect(self):
        """Test connection by getting bot info."""
        async def test(client):
            me = await client.get_me()
            print(f"[BOT] Connected as @{me.username}")
            return me
        self._run_with_client(test)
        print(f"[BOT-POOL] All workers can connect to channel {self.channel_id}")
        return self

    def upload_file(self, file_path, progress_callback=None):
        """Upload a single file to the channel."""
        async def upload(client):
            return await client.send_document(
                self.channel_id,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
        return self._run_with_client(upload)
    
    def upload_chunks_parallel(self, chunk_paths, max_concurrent=3):
        """Upload multiple chunks. Each chunk uses its own connection."""
        results = []
        for chunk_path in chunk_paths:
            try:
                result = self.upload_file(chunk_path)
                results.append(result)
            except Exception as e:
                print(f"[BOT] Chunk upload failed: {e}")
                raise
        return results

    def download_file(self, message_id, output_path, progress_callback=None):
        """Download a file from the channel."""
        async def download(client):
            msg = await client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document:
                raise Exception("File not found")
            return await client.download_media(
                msg,
                file_name=output_path,
                progress=progress_callback
            )
        return self._run_with_client(download)
    
    def delete_message(self, message_id):
        """Delete a message from the channel."""
        async def delete(client):
            await client.delete_messages(self.channel_id, message_id)
        return self._run_with_client(delete)
    
    def download_media(self, message_id, in_memory=False):
        """Download media, optionally to memory."""
        async def download(client):
            msg = await client.get_messages(self.channel_id, message_id)
            if not msg or not msg.document:
                return None
            return await client.download_media(msg, in_memory=in_memory)
        return self._run_with_client(download)

    def get_file_range(self, message_id, offset, limit):
        """Download a specific byte range (for streaming)."""
        async def stream(client):
            msg = await client.get_messages(str(self.channel_id), message_id)
            if not msg or not msg.document:
                return None
            chunk = b""
            async for data in client.stream_media(msg, offset=offset, limit=limit):
                chunk += data
            return chunk
        return self._run_with_client(stream)

    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        """Download multiple chunks sequentially."""
        results = []
        for msg_id in message_ids:
            try:
                async def download(client):
                    msg = await client.get_messages(self.channel_id, msg_id)
                    if not msg or not msg.document:
                        return None
                    return await client.download_media(msg, in_memory=False)
                result = self._run_with_client(download)
                results.append(result)
            except Exception as e:
                print(f"[BOT] Chunk download failed: {e}")
                results.append(None)
        return results
    
    def stop(self):
        """Nothing to stop - connections are closed after each operation."""
        pass


# ============================================================================
# TELEGRAM CLOUD - User session client (for user-mode auth)
# ============================================================================

class TelegramCloud:
    """Dynamic Telegram client for user sessions."""
    
    def __init__(self, session_string=None, api_id=None, api_hash=None):
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.storage_chat = Config.STORAGE_CHANNEL
        self.session_string = session_string
        self._connected = False
        self._resolved_chat_id = None
        self.storage_chat_title = "My Cloud Storage"

    def _run_async(self, async_func):
        """Run async function with a fresh client."""
        async def wrapper():
            if self.session_string:
                client = Client(
                    "telecloud_user",
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    session_string=self.session_string,
                    in_memory=True,
                    no_updates=True
                )
            else:
                client = Client(
                    Config.SESSION_NAME,
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    workdir=Config.BASE_DIR,
                    no_updates=True
                )
            
            try:
                await client.start()
                return await async_func(client)
            finally:
                try:
                    await client.stop()
                except:
                    pass
        
        return asyncio.run(wrapper())

    def connect(self):
        if not self._connected:
            async def work(client):
                return await client.get_me()
            self._run_async(work)
            self._connected = True
            self._resolve_chat()
        return self

    def _resolve_chat(self):
        try:
            async def work(client):
                return await client.get_chat(self.storage_chat)
            chat = self._run_async(work)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Private Chat')
        except Exception:
            async def work_me(client):
                return await client.get_chat("me")
            chat = self._run_async(work_me)
            self._resolved_chat_id = chat.id
            self.storage_chat_title = "Saved Messages"

    def upload_file(self, file_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        async def work(client):
            return await client.send_document(
                target,
                document=file_path,
                file_name=os.path.basename(file_path),
                progress=progress_callback
            )
        return self._run_async(work)

    def download_file(self, message_id, output_path, progress_callback=None):
        target = self._resolved_chat_id or self.storage_chat
        async def work(client):
            message = await client.get_messages(target, message_id)
            if not message or not message.document:
                raise Exception("File not found.")
            return await client.download_media(
                message,
                file_name=output_path,
                progress=progress_callback
            )
        return self._run_async(work)

    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        async def work(client):
            await client.delete_messages(target, message_id)
        self._run_async(work)

    def download_media(self, message_id, in_memory=False):
        target = self._resolved_chat_id or self.storage_chat
        async def work(client):
            msg = await client.get_messages(target, message_id)
            if not msg or not msg.document:
                return None
            return await client.download_media(msg, in_memory=in_memory)
        return self._run_async(work)

    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        async def work():
            temp_client = Client(":memory:", api_id=api_id, api_hash=api_hash, in_memory=True)
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
        return asyncio.run(work())

    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        async def work():
            await temp_client.sign_in(phone, code_hash, code)
            session_str = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            return session_str, me.id
        return asyncio.run(work())

    def stop(self):
        self._connected = False


# Global bot instance
_bot_instance = None

def get_bot_client():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
