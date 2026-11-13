"""Intent Gateway — Configuration via environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
ENV_PATH = ROOT_DIR / ".env" if (ROOT_DIR / ".env").exists() else BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """All config from .env or environment variables."""

    # Channel3
    channel3_api_key: str = ""

    # PayPal Sandbox
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str = ""

    # LLM
    llm_provider: str = "stub"  # "openai" | "gemini" | "anthropic" | "stub"
    openai_api_key: str = ""
    google_ai_api_key: str = ""
    anthropic_api_key: str = ""

    # Rate Limits
    rate_limit_per_15min: int = 5
    rate_limit_per_day: int = 30
    global_channel3_daily_cap: int = 250
    global_llm_daily_cap: int = 400

    # Cache
    channel3_cache_ttl_seconds: int = 3600

    # Cryptographic Mandates & Authentication
    admin_api_key: str = "admin_super_secret_test_key"
    demo_agent_key: str = "demo_agent_secret_test_key"
    mandate_signing_key: str = ""
    price_drift_tolerance: str = "0.01"
    # CSRF: stateless HMAC secret for approval confirmation pages.
    # Required in production — set a long random value (e.g. openssl rand -hex 32).
    csrf_secret: str = "dev_csrf_secret_change_me_in_production"

    # App Environment & Mode
    app_env: str = "development"  # "development" | "production" | "test"
    app_mode: str = "demo"  # "demo" | "admin"
    debug: bool = False
    public_base_url: str = ""  # Base URL for human supervisor approval links

    # Database & Storage
    database_path: str = ""
    database_url: str = ""
    web_concurrency: int = 1

    # Per-Visitor Demo Sandbox
    session_secret: str = "dev_session_secret_change_me_in_production"
    session_ttl_hours: int = 24
    session_rate_limit_per_hour: int = 30

    model_config = {
        "env_file": str(ENV_PATH),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
