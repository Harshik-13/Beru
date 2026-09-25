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


settings = Settings()
