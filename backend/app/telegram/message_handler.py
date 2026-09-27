"""
Telegram Message Handler — Personal Alpha.

Handles inbound Telegram messages and routes them through the existing
Beru intelligence pipeline (ConversationService).
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from uuid import UUID

from app.intelligence.models.context import StudentContext, StudentProfile
from app.intelligence.services.conversation import ConversationService
from app.repositories.student import StudentRepository
from app.security.context import AuthenticatedIdentity, UnauthenticatedIdentity
from app.telegram.auth import TelegramIdentityResolver, TelegramIncomingIdentity
from app.telegram.bot_adapter import TelegramBotAdapter
from app.telegram.models import IncomingTelegramMessage, OutgoingTelegramMessage, TelegramContactIdentity


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
        identity_resolver: TelegramIdentityResolver,
        conversation_service: ConversationService,
        student_repo: StudentRepository,
        session_factory,
        config: TelegramMessageHandlerConfig | None = None,
    ):
        self._adapter = adapter
        self._identity_resolver = identity_resolver
        self._conversation_service = conversation_service
        self._student_repo = student_repo
        self._session_factory = session_factory
        self._config = config or TelegramMessageHandlerConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._processed_keys: set[str] = set()

    async def start(self) -> None:
        """Start processing messages from the Telegram adapter."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_messages())
        logging.info("Telegram message handler started")

    async def stop(self) -> None:
        """Stop processing messages."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logging.info("Telegram message handler stopped")

    async def _process_messages(self) -> None:
        """Process messages from the Telegram adapter."""
        try:
            async for message in self._adapter.incoming_messages():
                if not self._running:
                    break
                try:
                    await self._handle_message(message)
                except Exception as e:
                    logging.exception(f"Error handling message: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.exception(f"Error in message processing loop: {e}")

    async def _handle_message(self, message: IncomingTelegramMessage) -> None:
        """Handle a single inbound Telegram message."""
        # 1. Idempotency check
        idempotency_key = message.get_idempotency_key()
        if await self._is_processed(idempotency_key):
            logging.debug(f"Skipping duplicate message: {idempotency_key}")
            return

        # 2. Skip /start command (handled by adapter for linking flow)
        if message.text and message.text.strip() == "/start":
            logging.debug("Skipping /start command (handled by linking flow)")
            return

        # 3. Skip non-text messages for now
        if message.message_type != "text" or not message.text:
            logging.debug(f"Skipping non-text message type: {message.message_type}")
            return

        # 4. Resolve Telegram identity to AuthenticatedIdentity
        incoming_identity = TelegramIncomingIdentity.from_contact(message.from_contact)
        auth_result = await self._identity_resolver.resolve(incoming_identity)

        if isinstance(auth_result, UnauthenticatedIdentity):
            # Unlinked user - send polite rejection
            await self._send_unlinked_response(message.chat_id)
            return

        # 5. Authenticated - process through conversation pipeline
        student_id = auth_result.student_id

        # 6. Get or create student profile
        async with self._session_factory() as session:
            student_repo = StudentRepository(session)
            student = await student_repo.get_or_create(student_id)

            # Create student profile
            profile = self._create_student_profile(student)

            # 7. Create student context
            student_context = self._create_student_context(student_id, profile)

            # 8. Process message through conversation pipeline
            response, _ = await self._conversation_service.process_message(
                student_context, message.text
            )

            # 9. Send response via Telegram adapter
            await self._send_response(message.chat_id, response)

        # 10. Mark as processed (idempotency)
        await self._mark_processed(message.get_idempotency_key())

    async def _is_processed(self, idempotency_key: str) -> bool:
        """Check if message was already processed."""
        return idempotency_key in self._processed_keys

    async def _mark_processed(self, idempotency_key: str) -> None:
        """Mark message as processed."""
        self._processed_keys.add(idempotency_key)

    def _create_student_profile(self, student) -> StudentProfile:
        """Create a basic student profile from Student model."""
        return StudentProfile(
            student_id=student.id,
            name=None,
        )

    def _create_student_context(self, student_id: UUID, profile: StudentProfile) -> StudentContext:
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
            "Please link your account first by sending /start and following the linking instructions."
        )
        await self._send_response(chat_id, message)

    async def _send_response(self, chat_id: str, text: str) -> None:
        """Send response message via Telegram adapter."""
        try:
            from_contact = self._adapter._our_identity or self._get_bot_identity()

            outgoing = OutgoingTelegramMessage(
                to_contact=TelegramContactIdentity(
                    provider="telegram_bot",
                    provider_user_id=chat_id,
                ),
                from_contact=from_contact,
                message_type="text",
                text=text,
                chat_id=chat_id,
            )

            await self._adapter.send_message(outgoing)
        except Exception as e:
            logging.exception(f"Failed to send Telegram response: {e}")

    def _get_bot_identity(self) -> TelegramContactIdentity:
        """Get bot identity for outgoing messages."""
        return self._adapter._our_identity or TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="",
        )