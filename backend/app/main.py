from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.intelligence.services.rate_limiter import (
    RateLimitConfig,
    create_rate_limiter,
)
from app.telegram import telegram_provider_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_rate_limiter(
        RateLimitConfig(
            max_requests=settings.llm_rate_limit_max_requests,
            window_seconds=settings.llm_rate_limit_window_seconds,
        )
    )

    # Initialize Telegram adapter if enabled
    if settings.telegram_enabled:
        if not settings.telegram_bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is required when TELEGRAM_ENABLED=true"
            )

        provider_class = telegram_provider_registry.get("telegram_bot")
        telegram_adapter = provider_class()

        from app.telegram.provider import TelegramProviderConfig

        await telegram_adapter.initialize(
            TelegramProviderConfig(
                provider_name="telegram_bot",
                config={
                    "bot_token": settings.telegram_bot_token,
                    "poll_timeout": settings.telegram_poll_timeout_seconds,
                    "drop_pending_updates": settings.telegram_drop_pending_updates,
                },
            )
        )
        await telegram_adapter.start()
        app.state.telegram_adapter = telegram_adapter

    yield

    # Shutdown
    if hasattr(app.state, "telegram_adapter"):
        await app.state.telegram_adapter.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.app_env.value != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(health_router)
