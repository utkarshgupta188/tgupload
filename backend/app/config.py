from pydantic_settings import BaseSettings
from pydantic import AnyUrl
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    API_PASSWORD: Optional[str] = None
    DATABASE_URL: Optional[str] = None  # e.g., postgres://... for Supabase; if None, use SQLite file
    BASE_URL: Optional[AnyUrl] = None  # public base URL of backend (for CORS if needed)
    TG_CHAT_ID: Optional[str] = None  # target chat (channel/group) id where files are stored
    TELEGRAM_UPLOAD_MODE: str = "bot"  # "bot" (50MB) or "user" (2GB via MTProto)
    # MTProto (user mode) credentials
    TG_API_ID: Optional[int] = None
    TG_API_HASH: Optional[str] = None
    TG_SESSION_STRING: Optional[str] = None
    # Timeouts and networking
    UPLOAD_TIMEOUT_SECONDS: int = 1800  # how long to wait for a single upload to complete (user mode)
    TELEGRAM_HTTP_TIMEOUT_SECONDS: int = 300  # HTTP timeout for Bot API calls

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()