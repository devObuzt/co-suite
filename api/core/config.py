from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings

_here = Path(__file__).resolve().parent.parent  # api/


class Settings(BaseSettings):
    app_name: str = "co-Suite API"
    debug: bool = False

    # Database — Railway provides postgresql://, asyncpg needs postgresql+asyncpg://
    database_url: str = "postgresql+asyncpg://cosuite:cosuite@localhost:5432/cosuite"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Generation queue — concurrent jobs per worker process
    generation_worker_concurrency: int = 4

    # Remotion render — browser tabs rendering in parallel; higher values
    # exhaust worker memory on long/4K sources
    remotion_render_concurrency: int = 2

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
    openai_api_key: str = ""
    ai_text_provider: str = "anthropic"  # anthropic | openai
    anthropic_text_model: str = "claude-sonnet-4-6"
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"
    openai_text_model: str = "gpt-5.1"
    openai_fast_model: str = "gpt-4.1"
    google_api_key: str = ""
    google_image_model: str = "gemini-3.1-flash-preview-image-generation"
    google_video_model: str = "veo-3.1-fast-generate-preview"
    openai_image_model: str = "gpt-image-1.5"
    fal_key: str = ""
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_login_customer_id: str = ""
    google_ads_customer_id: str = ""
    google_ads_refresh_token: str = ""
    serpapi_api_key: str = ""
    serpapi_cost_per_search_usd: float = 0.0
    google_ads_keyword_planner_cost_usd: float = 0.0

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

    # Observability / incident alerts
    log_format: str = "json"  # json | text
    environment: str = "local"
    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""
    telegram_admin_chat_id: str = ""
    observability_alerts_enabled: bool = True
    provider_limit_alert_min_wait_seconds: int = 60
    failed_job_alerts_enabled: bool = True
    admin_email: str = ""

    class Config:
        env_file = str(_here / ".env")
        extra = "ignore"


settings = Settings()
