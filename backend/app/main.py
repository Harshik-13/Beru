import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.core.database import async_session_factory
from app.intelligence.providers import create_llm_provider
from app.intelligence.services.rate_limiter import (
    RateLimitConfig,
    create_rate_limiter,
)
from app.telegram import telegram_provider_registry
from app.telegram.message_handler import (
    TelegramMessageHandler,
    TelegramMessageHandlerConfig,
)
from app.workers.briefing_scheduler import create_briefing_scheduler

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    create_rate_limiter(
        RateLimitConfig(
            max_requests=settings.llm_rate_limit_max_requests,
            window_seconds=settings.llm_rate_limit_window_seconds,
        )
    )

    # Initialize Telegram adapter if enabled
    telegram_message_handler = None
    telegram_adapter = None
    briefing_scheduler = None
    llm_provider = None
    try:
        if settings.telegram_enabled:
            if not settings.telegram_bot_token:
                raise RuntimeError(
                    "TELEGRAM_BOT_TOKEN is required when TELEGRAM_ENABLED=true"
                )

            logger.info("Initializing Telegram adapter...")
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
            logger.info("Telegram adapter initialized successfully")

            # Initialize LLM provider
            llm_provider = await create_llm_provider()
            if llm_provider:
                logger.info(f"LLM provider initialized: {llm_provider.provider_name}")
            else:
                logger.warning("No LLM provider configured, using mock")

            # Initialize message handler with live session factory
            telegram_message_handler = TelegramMessageHandler(
                adapter=telegram_adapter,
                session_factory=async_session_factory,
                llm_provider=llm_provider,
                config=TelegramMessageHandlerConfig(),
            )

            # Start the adapter and message handler
            logger.info("Starting Telegram adapter (long polling)...")
            await telegram_adapter.start()
            logger.info("Telegram adapter started (polling loop running)")

            logger.info("Starting Telegram message handler...")
            await telegram_message_handler.start()
            logger.info("Telegram message handler started")

            # Initialize and start briefing scheduler
            logger.info("Starting briefing scheduler...")
            briefing_scheduler = create_briefing_scheduler(
                session_factory=async_session_factory,
                telegram_adapter=telegram_adapter,
                interval_seconds=settings.briefing_scheduler_interval_seconds,
            )
            await briefing_scheduler.start()
            logger.info("Briefing scheduler started")

            app.state.telegram_adapter = telegram_adapter
            app.state.telegram_message_handler = telegram_message_handler
            app.state.briefing_scheduler = briefing_scheduler
            app.state.llm_provider = llm_provider

            logger.info("Application startup complete")
        else:
            logger.info("Telegram is disabled (TELEGRAM_ENABLED=false)")
    except Exception as e:
        logger.exception(f"Failed to start application: {e}")
        # Cleanup on startup failure
        if briefing_scheduler:
            await briefing_scheduler.stop()
        if telegram_message_handler:
            await telegram_message_handler.stop()
        if telegram_adapter:
            await telegram_adapter.stop()
        if llm_provider:
            await llm_provider.close()
        raise

    yield

    # Shutdown
    logger.info("Shutting down...")
    if hasattr(app.state, "llm_provider") and app.state.llm_provider:
        await app.state.llm_provider.close()
        logger.info("LLM provider closed")
    if hasattr(app.state, "briefing_scheduler") and app.state.briefing_scheduler:
        await app.state.briefing_scheduler.stop()
    if hasattr(app.state, "telegram_message_handler") and (
        app.state.telegram_message_handler
    ):
        await app.state.telegram_message_handler.stop()
    if hasattr(app.state, "telegram_adapter") and app.state.telegram_adapter:
        await app.state.telegram_adapter.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.app_env.value != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(health_router)
