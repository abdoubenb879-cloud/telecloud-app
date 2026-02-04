"""
TeleCloud Telegram Client - BULLETPROOF VERSION
Uses nest_asyncio to solve all asyncio/threading issues.
Simple, clean, works everywhere.
"""
import asyncio
import os
import traceback

# CRITICAL: Apply nest_asyncio FIRST before any async code
# This allows asyncio.run() to work inside existing event loops
import nest_asyncio
nest_asyncio.apply()

# Apply Pyrogram patch for 64-bit channel IDs
import app.pyrogram_patch
from pyrogram import Client
from pyrogram.errors import FloodWait
from .config import Config


class TelegramUploader:
    """
    Simple, stateless Telegram uploader.
    Each instance creates a fresh connection.
    Thread-safe and works in any context.
    """
    
    def __init__(self, bot_token=None, api_id=None, api_hash=None, channel_id=None):
        self.bot_token = bot_token
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH
        self.channel_id = channel_id or Config.STORAGE_CHANNEL_ID
        
        if not self.bot_token:
            raise ValueError("bot_token is required")
        if not self.channel_id:
            raise ValueError("channel_id is required")
        
        # Unique name for this uploader instance
        self._name = f"uploader_{id(self)}"
    
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
        """Test that the bot can connect to Telegram."""
        print(f"[UPLOADER] Testing connection...")
        
        async def _test():
            client = self._create_client()
            try:
                await client.start()
                me = await client.get_me()
                print(f"[UPLOADER] Connected as @{me.username}")
                return me
            finally:
                await client.stop()
        
        return asyncio.run(_test())
    
    def upload_file(self, file_path, progress_callback=None):
        """
        Upload a single file to the channel.
        Returns the message object from Telegram.
        """
        print(f"[UPLOADER] Uploading: {file_path}")
        print(f"[UPLOADER] To channel: {self.channel_id}")
        
        async def _upload():
            client = self._create_client()
            try:
                print(f"[UPLOADER] Starting client...")
                await client.start()
                print(f"[UPLOADER] Client started, uploading file...")
                
                result = await client.send_document(
                    chat_id=self.channel_id,
                    document=file_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback
                )
                
                print(f"[UPLOADER] Upload successful! Message ID: {result.id}")
                return result
            
            except FloodWait as e:
                print(f"[UPLOADER] Rate limited! Waiting {e.value} seconds...")
                await asyncio.sleep(e.value)
                # Retry
                result = await client.send_document(
                    chat_id=self.channel_id,
                    document=file_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback
                )
                print(f"[UPLOADER] Retry successful! Message ID: {result.id}")
                return result
            
            except Exception as e:
                print(f"[UPLOADER] Upload FAILED: {e}")
                traceback.print_exc()
                raise
            
            finally:
                try:
                    print(f"[UPLOADER] Stopping client...")
                    await client.stop()
                    print(f"[UPLOADER] Client stopped.")
                except Exception as stop_err:
                    print(f"[UPLOADER] Error stopping client: {stop_err}")
        
        return asyncio.run(_upload())
    
    def download_file(self, message_id, output_path, progress_callback=None):
        """Download a file from the channel."""
        print(f"[UPLOADER] Downloading message {message_id} to {output_path}")
        
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
        
        return asyncio.run(_download())
    
    def delete_message(self, message_id):
        """Delete a message from the channel."""
        print(f"[UPLOADER] Deleting message {message_id}")
        
        async def _delete():
            client = self._create_client()
            try:
                await client.start()
                await client.delete_messages(self.channel_id, message_id)
                print(f"[UPLOADER] Message deleted")
            finally:
                await client.stop()
        
        return asyncio.run(_delete())
    
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
        
        return asyncio.run(_download())
    
    def get_file_range(self, message_id, offset, limit):
        """Download a specific byte range (for streaming)."""
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
        
        return asyncio.run(_stream())


# ============================================================================
# BOT CLIENT MANAGER - Simple token rotation
# ============================================================================

class BotClient:
    """
    Manages multiple bot tokens with round-robin rotation.
    Creates fresh TelegramUploader for each operation.
    """
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
        
        # Fallback: scan environment
        if not self.bot_tokens:
            print("[BOT] Config.BOT_TOKENS empty, scanning environment...")
            self.bot_tokens = []
            for key, val in os.environ.items():
                if key.startswith("BOT_TOKEN") and key != "BOT_TOKENS":
                    token = val.strip()
                    if token and token not in self.bot_tokens:
                        self.bot_tokens.append(token)
                        print(f"[BOT] Found token from {key}")
        
        if not self.bot_tokens:
            raise ValueError("No BOT_TOKENS provided! Cannot start.")
        
        self._token_index = 0
        self._initialized = True
        print(f"[BOT] Initialized with {len(self.bot_tokens)} bot tokens")
    
    def _get_next_token(self):
        """Get next token using round-robin."""
        token = self.bot_tokens[self._token_index % len(self.bot_tokens)]
        self._token_index += 1
        return token
    
    def _create_uploader(self):
        """Create a fresh uploader with the next token."""
        return TelegramUploader(
            bot_token=self._get_next_token(),
            api_id=self.api_id,
            api_hash=self.api_hash,
            channel_id=self.channel_id
        )
    
    def connect(self):
        """Test connection with one of the bots."""
        uploader = self._create_uploader()
        uploader.test_connection()
        print(f"[BOT] Connection test successful!")
        return self
    
    def upload_file(self, file_path, progress_callback=None):
        """Upload a file using the next available bot."""
        uploader = self._create_uploader()
        return uploader.upload_file(file_path, progress_callback)
    
    def upload_chunks_parallel(self, chunk_paths, max_concurrent=3):
        """Upload multiple chunks sequentially (one bot per chunk)."""
        print(f"[BOT] Uploading {len(chunk_paths)} chunks...")
        results = []
        for i, chunk_path in enumerate(chunk_paths):
            print(f"[BOT] Chunk {i+1}/{len(chunk_paths)}: {chunk_path}")
            uploader = self._create_uploader()
            result = uploader.upload_file(chunk_path)
            results.append(result)
        print(f"[BOT] All {len(results)} chunks uploaded successfully!")
        return results
    
    def download_file(self, message_id, output_path, progress_callback=None):
        """Download a file."""
        uploader = self._create_uploader()
        return uploader.download_file(message_id, output_path, progress_callback)
    
    def delete_message(self, message_id):
        """Delete a message."""
        uploader = self._create_uploader()
        return uploader.delete_message(message_id)
    
    def download_media(self, message_id, in_memory=False):
        """Download media."""
        uploader = self._create_uploader()
        return uploader.download_media(message_id, in_memory)
    
    def get_file_range(self, message_id, offset, limit):
        """Get file range for streaming."""
        uploader = self._create_uploader()
        return uploader.get_file_range(message_id, offset, limit)
    
    def download_chunks_parallel(self, message_ids, max_concurrent=3):
        """Download multiple chunks."""
        results = []
        for msg_id in message_ids:
            uploader = self._create_uploader()
            result = uploader.download_media(msg_id)
            results.append(result)
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
            
            asyncio.run(_connect())
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
            
            chat = asyncio.run(_resolve())
            self._resolved_chat_id = chat.id
            self.storage_chat_title = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Private Chat')
        except Exception:
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
        
        return asyncio.run(_upload())
    
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
        
        return asyncio.run(_download())
    
    def delete_message(self, message_id):
        target = self._resolved_chat_id or self.storage_chat
        
        async def _delete():
            client = self._create_client()
            await client.start()
            await client.delete_messages(target, message_id)
            await client.stop()
        
        asyncio.run(_delete())
    
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
        
        return asyncio.run(_download())
    
    @staticmethod
    def send_login_code(api_id, api_hash, phone):
        async def _send():
            temp_client = Client(":memory:", api_id=api_id, api_hash=api_hash, in_memory=True)
            await temp_client.connect()
            code = await temp_client.send_code(phone)
            return temp_client, code.phone_code_hash
        
        return asyncio.run(_send())
    
    @staticmethod
    def complete_login(temp_client, phone, code_hash, code):
        async def _complete():
            await temp_client.sign_in(phone, code_hash, code)
            session_str = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            return session_str, me.id
        
        return asyncio.run(_complete())
    
    def stop(self):
        self._connected = False


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_bot_instance = None

def get_bot_client():
    """Get the global BotClient instance."""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = BotClient()
    return _bot_instance
