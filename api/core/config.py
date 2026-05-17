from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings

_here = Path(__file__).resolve().parent.parent  # api/


class Settings(BaseSettings):
    app_name: str = "co-Suite API"
    debug: bool = False

    # Database — Railway provides postgresql://, asyncpg needs postgresql+asyncpg://
    database_url: str = "postgresql+asyncpg://cosuite:cosuite@localhost:5432/cosuite"

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_db_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Auth
    secret_key: str = "change-this-secret-key-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Frontend — comma-separated list of allowed origins
    frontend_url: str = "http://localhost:3000"

    # AI Keys
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # Cloudflare R2
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""

    # Meta
    meta_app_id: str = ""
    meta_app_secret: str = ""

    # Billing — Morning
    morning_api_key: str = ""
    morning_webhook_secret: str = ""
    morning_subscribe_url: str = ""   # fill in when Morning provides the payment page URL
    morning_pay_url: str = ""         # fill in when Morning provides the pay-balance page URL

    class Config:
        env_file = str(_here / ".env")
        extra = "ignore"


settings = Settings()
