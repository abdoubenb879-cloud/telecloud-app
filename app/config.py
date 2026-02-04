import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class to store app settings."""
    API_ID = int(os.getenv("API_ID", 0))
    API_HASH = os.getenv("API_HASH", "")
    PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")
    SESSION_NAME = os.getenv("SESSION_NAME", "telecloud_session")
    STORAGE_CHANNEL = os.getenv("STORAGE_CHANNEL", "me")
    
    # Bot Mode (NEW - Centralized storage)
    # Bot Mode (NEW - Centralized storage)
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # Support multiple tokens for scaling (comma separated OR separate env vars)
    BOT_TOKENS = [t.strip() for t in os.getenv("BOT_TOKENS", "").split(",") if t.strip()]
    
    # Also scan for BOT_TOKEN1, BOT_TOKEN2, etc.
    for key, val in os.environ.items():
        if key.startswith("BOT_TOKEN") and key != "BOT_TOKENS" and val.strip():
            if val.strip() not in BOT_TOKENS:
                BOT_TOKENS.append(val.strip())
    
    # Fallback to single token if list is empty
    if not BOT_TOKENS and BOT_TOKEN:
        BOT_TOKENS = [BOT_TOKEN]
    
    STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", 0)) if os.getenv("STORAGE_CHANNEL_ID") else None
    
    # Cloud / Multi-User settings
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    MULTI_USER = os.getenv("MULTI_USER", "false").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "telecloud_secret_vault") # For session encryption
    
    # 20MB chunks for better parallelization in cloud mode
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 20 * 1024 * 1024))
    
    # Directories
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
    DATABASE_PATH = os.path.join(BASE_DIR, "cloud_metadata_v2.db")

