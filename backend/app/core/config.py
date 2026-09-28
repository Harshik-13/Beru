from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "beru"
    app_version: str = "0.1.0"
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"  # noqa: S105
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://beru:changeme@localhost:5432/beru"

    # LLM Provider
    llm_provider: str = "mock"
    llm_model: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_retry_base_delay: float = 1.0

    # LLM Rate Limiting (per student)
    llm_rate_limit_max_requests: int = 30
    llm_rate_limit_window_seconds: int = 60

    # Portal Integration
    portal_base_url: str = "https://automation.vnrvjiet.ac.in"
    portal_credential_encryption_key: str = ""

    # Telegram Bot
    telegram_enabled: bool = False
    telegram_bot_token: str = ""  # Required if telegram_enabled=True, no default
    telegram_poll_timeout_seconds: int = 30
    telegram_drop_pending_updates: bool = True

    # Briefing Scheduler
    briefing_scheduler_interval_seconds: int = 60
    briefing_default_time: str = "08:30"
    briefing_default_timezone: str = "Asia/Kolkata"


settings = Settings()
