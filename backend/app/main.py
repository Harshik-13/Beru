from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.core.database import async_session_factory
from app.intelligence.services.rate_limiter import (
    RateLimitConfig,
    create_rate_limiter,
)
from app.repositories.telegram_linking_challenge import (
    TelegramLinkingChallengeRepository,
)
from app.telegram import telegram_provider_registry
from app.telegram.message_handler import (
    TelegramMessageHandler,
    TelegramMessageHandlerConfig,
)


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
    telegram_message_handler = None
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

        # Create challenge repository and set on adapter for /start linking flow
        async with async_session_factory() as session:
            challenge_repo = TelegramLinkingChallengeRepository(session)
            telegram_adapter.set_challenge_repository(challenge_repo)

        # Initialize and start message handler
        async with async_session_factory() as session:
            from app.intelligence.services.attendance_service import AttendanceService
            from app.intelligence.services.context_builder import ContextBuilder
            from app.intelligence.services.conversation import ConversationService
            from app.intelligence.services.timetable_service import TimetableService
            from app.repositories.student import StudentRepository
            from app.repositories.telegram_identity import TelegramIdentityRepository
            from app.repositories.telegram_linking_challenge import (
                TelegramLinkingChallengeRepository,
            )
            from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
            from app.security.student_resolver import DatabaseStudentResolver
            from app.telegram.auth import TelegramIdentityResolver
            from app.intelligence.services.context_builder import ContextBuilder
            from app.intelligence.services.timetable_service import TimetableService
            from app.intelligence.services.attendance_service import AttendanceService
            from app.repositories.telegram_identity import TelegramIdentityRepository

            # Create repositories
            whatsapp_identity_repo = WhatsAppIdentityRepository(session)
            telegram_identity_repo = TelegramIdentityRepository(session)
            student_repo = StudentRepository(session)
            _ = TelegramLinkingChallengeRepository(session)

            # Create services
            student_resolver = DatabaseStudentResolver(
                whatsapp_identity_repo=whatsapp_identity_repo,
                telegram_identity_repo=telegram_identity_repo,
            )
            identity_resolver = TelegramIdentityResolver(student_resolver)

            # Create conversation service dependencies
            timetable_service = TimetableService(session)
            attendance_service = AttendanceService(session)
            context_builder = ContextBuilder()
            conversation_service = ConversationService(
                tool_registry_instance=None,  # Use default
                context_builder=context_builder,
                llm_provider=None,  # Use mock
                timetable_service=timetable_service,
                attendance_service=attendance_service,
            )

            # Create message handler
            message_handler_config = TelegramMessageHandlerConfig()
            telegram_message_handler = TelegramMessageHandler(
                adapter=telegram_adapter,
                identity_resolver=identity_resolver,
                conversation_service=conversation_service,
                student_repo=student_repo,
                session_factory=async_session_factory,
                config=message_handler_config,
            )

        # Start the adapter and message handler
        await telegram_adapter.start()
        await telegram_message_handler.start()

        app.state.telegram_adapter = telegram_adapter
        app.state.telegram_message_handler = telegram_message_handler

    yield

    # Shutdown
    if hasattr(app.state, "telegram_message_handler") and (
        app.state.telegram_message_handler
    ):
        await app.state.telegram_message_handler.stop()
    if hasattr(app.state, "telegram_adapter") and app.state.telegram_adapter:
        await app.state.telegram_adapter.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.app_env.value != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(health_router)