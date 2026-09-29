"""
Telegram Message Handler — Personal Alpha.

Handles inbound Telegram messages and routes them through the existing
Beru intelligence pipeline (ConversationService) and Telegram linking flow.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.providers.base import LLMProvider
from app.intelligence.services.attendance_service import AttendanceService
from app.intelligence.services.context_builder import ContextBuilder
from app.intelligence.services.conversation import ConversationService
from app.intelligence.services.timetable_service import TimetableService
from app.models.student import Student
from app.repositories.student import StudentRepository
from app.repositories.telegram_identity import TelegramIdentityRepository
from app.repositories.telegram_linking_challenge import (
    TelegramLinkingChallengeRepository,
)
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.security.audit import AuditService
from app.security.context import UnauthenticatedIdentity
from app.security.student_resolver import DatabaseStudentResolver
from app.telegram.auth import TelegramIdentityResolver, TelegramIncomingIdentity
from app.telegram.bot_adapter import TelegramBotAdapter
from app.telegram.linking_service import TelegramLinkingService
from app.telegram.models import (
    IncomingTelegramMessage,
    OutgoingTelegramMessage,
    TelegramContactIdentity,
    TelegramMessageType,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramMessageHandlerConfig:
    """Configuration for Telegram message handler."""

    max_history: int = 10
    default_student_name: str = "Student"


class TelegramMessageHandler:
    """
    Handles inbound Telegram messages and routes them through the existing
    Beru intelligence pipeline.
    """

    def __init__(
        self,
        adapter: TelegramBotAdapter,
        session_factory: Callable[..., Any],
        identity_resolver: TelegramIdentityResolver | None = None,
        conversation_service: ConversationService | None = None,
        student_repo: StudentRepository | None = None,
        llm_provider: LLMProvider | None = None,
        config: TelegramMessageHandlerConfig | None = None,
    ):
        self._adapter = adapter
        self._session_factory = session_factory
        self._identity_resolver = identity_resolver
        self._conversation_service = conversation_service
        self._student_repo = student_repo
        self._llm_provider = llm_provider
        self._config = config or TelegramMessageHandlerConfig()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._processed_keys: set[str] = set()

    async def start(self) -> None:
        """Start processing messages from the Telegram adapter."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_messages())
        logger.info("Telegram message handler started")

    async def stop(self) -> None:
        """Stop processing messages."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Telegram message handler stopped")

    async def _process_messages(self) -> None:
        """Process messages from the Telegram adapter."""
        try:
            async for message in self._adapter.incoming_messages():
                if not self._running:
                    break
                try:
                    await self._handle_message(message)
                except Exception as e:
                    logger.exception(f"Error handling message: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Error in message processing loop: {e}")

    async def _handle_message(self, message: IncomingTelegramMessage) -> None:
        """Handle a single inbound Telegram message."""
        # 1. Idempotency check
        idempotency_key = message.get_idempotency_key()
        if await self._is_processed(idempotency_key):
            logger.debug(f"Skipping duplicate message: {idempotency_key}")
            return

        # 2. Check for /start command (linking onboarding)
        if message.text and message.text.strip() == "/start":
            await self._handle_start_command(message)
            await self._mark_processed(idempotency_key)
            return

        # 3. Skip non-text messages for now
        if message.message_type != TelegramMessageType.TEXT or not message.text:
            logger.debug(f"Skipping non-text message type: {message.message_type}")
            return

        # 4. Resolve identity and process conversation inside request-scoped session
        async with self._session_factory() as session:
            if self._identity_resolver is not None:
                identity_resolver = self._identity_resolver
            else:
                whatsapp_identity_repo = WhatsAppIdentityRepository(session)
                telegram_identity_repo = TelegramIdentityRepository(session)
                student_resolver = DatabaseStudentResolver(
                    whatsapp_identity_repo=whatsapp_identity_repo,
                    telegram_identity_repo=telegram_identity_repo,
                )
                identity_resolver = TelegramIdentityResolver(student_resolver)

            incoming_identity = TelegramIncomingIdentity.from_contact(
                message.from_contact
            )
            auth_result = await identity_resolver.resolve(incoming_identity)

            if isinstance(auth_result, UnauthenticatedIdentity):
                logger.warning(
                    "Unlinked Telegram user [id=%s, name=%s]: %s",
                    message.from_contact.provider_user_id,
                    message.from_contact.normalized_identifier,
                    auth_result.reason,
                )
                await self._send_unlinked_response(message.chat_id)
                await self._mark_processed(idempotency_key)
                return

            # 5. Authenticated - load student profile
            student_id = auth_result.student_id
            student_repo = self._student_repo or StudentRepository(session)
            student = await student_repo.get_or_create(student_id)

            profile = self._create_student_profile(student)
            student_context = self._create_student_context(student_id, profile)

            # 6. Execute conversation pipeline
            if self._conversation_service is not None:
                conversation_service = self._conversation_service
            else:
                timetable_service = TimetableService(session)
                attendance_service = AttendanceService(session)
                conversation_service = ConversationService(
                    tool_registry_instance=None,
                    context_builder=ContextBuilder(),
                    llm_provider=self._llm_provider,
                    timetable_service=timetable_service,
                    attendance_service=attendance_service,
                )

            logger.info(
                "Routing message to conversation pipeline for student_id=%s: %r",
                student_id,
                message.text,
            )
            response, _ = await conversation_service.process_message(
                student_context, message.text
            )
            logger.info(
                "Generated response for student_id=%s: %r...",
                student_id,
                response[:60],
            )
            await self._send_response(message.chat_id, response)

        # 7. Mark as processed (idempotency)
        await self._mark_processed(idempotency_key)

    async def _handle_start_command(self, message: IncomingTelegramMessage) -> None:
        """Handle /start: generate linking challenge and send onboarding message."""
        telegram_user_id = message.from_contact.provider_user_id
        logger.info(
            "Handling /start for Telegram user_id=%s (chat_id=%s)",
            telegram_user_id,
            message.chat_id,
        )

        async with self._session_factory() as session:
            challenge_repo = TelegramLinkingChallengeRepository(session)
            telegram_repo = TelegramIdentityRepository(session)
            student_repo = StudentRepository(session)
            audit_service = AuditService(session)
            linking_service = TelegramLinkingService(
                challenge_repo=challenge_repo,
                telegram_identity_repo=telegram_repo,
                student_repo=student_repo,
                audit_service=audit_service,
            )

            challenge_token = await linking_service.create_linking_challenge(
                telegram_user_id=telegram_user_id
            )

        onboarding_text = (
            f"Welcome to Beru! 🎓\n\n"
            f"To link your Telegram account to your student profile:\n\n"
            f"1. Open the Beru app and log in\n"
            f"2. Go to Settings → Telegram Linking\n"
            f"3. Enter this challenge code: <code>{challenge_token}</code>\n\n"
            f"This code expires in 10 minutes and can only be used once.\n\n"
            f"Once linked, you'll receive timetable updates, attendance alerts, "
            f"and more directly here."
        )
        await self._send_response(message.chat_id, onboarding_text, parse_mode="HTML")

    async def _is_processed(self, idempotency_key: str) -> bool:
        """Check if message was already processed."""
        return idempotency_key in self._processed_keys

    async def _mark_processed(self, idempotency_key: str) -> None:
        """Mark message as processed."""
        self._processed_keys.add(idempotency_key)

    def _create_student_profile(self, student: Student) -> StudentProfile:
        """Create a student profile from Student model."""
        return StudentProfile(
            student_id=student.id,
            name=student.name,
            attendance_target=student.attendance_target,
            briefing_time=student.briefing_time,
            timezone=student.timezone or "Asia/Kolkata",
        )

    def _create_student_context(
        self, student_id: UUID, profile: StudentProfile
    ) -> StudentContext:
        """Create a StudentContext for the conversation service."""
        return StudentContext(
            student_id=student_id,
            profile=profile,
            conversation=ConversationContext(student_id=student_id),
        )

    async def _send_unlinked_response(self, chat_id: str) -> None:
        """Send response to unlinked user."""
        message = (
            "I don't recognize this Telegram account. "
            "Please link your account first by sending /start "
            "and following the linking instructions."
        )
        await self._send_response(chat_id, message)

    async def _send_response(
        self, chat_id: str, text: str, parse_mode: str | None = None
    ) -> None:
        """Send response message via Telegram adapter."""
        try:
            from_contact = await self._get_bot_identity()

            outgoing = OutgoingTelegramMessage(
                to_contact=TelegramContactIdentity(
                    provider="telegram_bot",
                    provider_user_id=chat_id,
                ),
                from_contact=from_contact,
                message_type=TelegramMessageType.TEXT,
                text=text,
                chat_id=chat_id,
                parse_mode=parse_mode,
            )

            await self._adapter.send_message(outgoing)
        except Exception as e:
            logger.exception(f"Failed to send Telegram response: {e}")

    async def _get_bot_identity(self) -> TelegramContactIdentity:
        """Get bot identity for outgoing messages."""
        our_identity = None
        if hasattr(self._adapter, "get_our_identity"):
            with contextlib.suppress(Exception):
                our_identity = await self._adapter.get_our_identity()

        return our_identity or TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="",
        )
