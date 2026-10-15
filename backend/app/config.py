"""Intent Gateway — Configuration via environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """All config from .env or environment variables."""

    # Channel3
    channel3_api_key: str = ""

    # PayPal Sandbox
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

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

    model_config = {
        "env_file": str(ENV_PATH),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
