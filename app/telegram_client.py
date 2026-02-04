"""
TeleCloud Telegram Client - SIMPLE THREAD-LOCAL LOOP VERSION
Each thread creates its own event loop and runs async code directly.
No cross-thread communication, no deadlocks.
"""
import asyncio
import os
import threading
import traceback

# Apply Pyrogram patch for 64-bit channel IDs
import app.pyrogram_patch
from pyrogram import Client
from pyrogram.errors import FloodWait
from .config import Config


def run_async(coro, timeout=300):
    """
    Run async code in the current thread with a fresh event loop.
    Works in any thread - main thread, gunicorn workers, background threads.
    """
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Run with timeout
        return loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout)
        )
    except asyncio.TimeoutError:
        print(f"[ASYNC] Operation timed out after {timeout}s")
        raise
    except Exception as e:
        print(f"[ASYNC] Error: {e}")
        traceback.print_exc()
        raise
    finally:
        # Clean up the loop
        try:
            # Cancel all pending tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # Give tasks time to clean up
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except:
            pass
        loop.close()


class TelegramUploader:
    """
    Simple Telegram uploader.
    Each operation creates its own event loop and client.
    Thread-safe and works anywhere.
    """
    
    def __init__(self, bot_token, api_id=None, api_hash=None, channel_id=None):
        self.bot_token = bot_token
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.channel_id = channel_id or Config.STORAGE_CHANNEL_ID
        self._name = f"bot_{id(self)}_{threading.current_thread().name}"
    
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
        print(f"[UPLOADER] Testing connection...")
        
        async def _test():
            print(f"[UPLOADER] Creating client...")
            client = self._create_client()
            try:
                print(f"[UPLOADER] Calling client.start()...")
                await client.start()
                print(f"[UPLOADER] Client started!")
                me = await client.get_me()
                print(f"[UPLOADER] Connected as @{me.username}")
                return me
            finally:
                print(f"[UPLOADER] Stopping client...")
                await client.stop()
                print(f"[UPLOADER] Client stopped.")
        
        return run_async(_test(), timeout=60)
    
    def upload_file(self, file_path, progress_callback=None):
        """Upload a file to the channel."""
        print(f"[UPLOADER] Uploading: {file_path}")
        print(f"[UPLOADER] To channel: {self.channel_id}")
        print(f"[UPLOADER] Thread: {threading.current_thread().name}")
        
        async def _upload():
            print(f"[UPLOADER] Creating upload client...")
            client = self._create_client()
            try:
                print(f"[UPLOADER] Starting upload client...")
                await client.start()
                print(f"[UPLOADER] Client ready, sending document...")
                
                result = await client.send_document(
                    chat_id=self.channel_id,
                    document=file_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback
                )
                
                print(f"[UPLOADER] *** UPLOAD SUCCESS! *** Message ID: {result.id}")
                return result
            
            except FloodWait as e:
                print(f"[UPLOADER] FloodWait: {e.value}s, retrying...")
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
                print(f"[UPLOADER] Stopping upload client...")
                await client.stop()
                print(f"[UPLOADER] Upload client stopped.")
        
        return run_async(_upload(), timeout=300)
    
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
        
        return run_async(_download(), timeout=300)
    
    def delete_message(self, message_id):
        """Delete a message from the channel."""
        async def _delete():
            client = self._create_client()
            try:
                await client.start()
                await client.delete_messages(self.channel_id, message_id)
                print(f"[UPLOADER] Message {message_id} deleted")
            finally:
                await client.stop()
        
        return run_async(_delete(), timeout=60)
    
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
        
        return run_async(_download(), timeout=300)
    
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
        
        return run_async(_stream(), timeout=120)


class BotClient:
    """Manages multiple bot tokens with round-robin."""
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
        with self._lock:
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
            
            run_async(_connect())
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
            
            chat = run_async(_resolve())
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
        
        return run_async(_upload(), timeout=300)
    
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
        
        return run_async(_download(), timeout=300)
    
    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _delete():
            client = self._create_client()
            await client.start()
            await client.delete_messages(target, message_id)
            await client.stop()
        
        run_async(_delete())
    
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
        
        return run_async(_download(), timeout=300)
    
    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        async def _send():
            temp_client = Client(":memory:", api_id=api_id, api_hash=api_hash, in_memory=True)
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
        
        return run_async(_send())
    
    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        async def _complete():
            await temp_client.sign_in(phone, code_hash, code)
            session_str = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            return session_str, me.id
        
        return run_async(_complete())
    
    def stop(self):
        self._connected = False


# Global instance
_bot_instance = None

def get_bot_client():
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
