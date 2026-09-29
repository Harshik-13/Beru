"""
Telegram Message Handler — Personal Alpha.

Handles inbound Telegram messages and routes them through the existing
Beru intelligence pipeline (ConversationService) and Telegram linking flow.
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from app.models.timetable import Timetable, TimetableStatus
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
        self._conversation_contexts: dict[UUID, ConversationContext] = {}

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

        # 3. Check message type
        supported_types = {
            TelegramMessageType.TEXT,
            TelegramMessageType.DOCUMENT,
            TelegramMessageType.PHOTO,
        }
        if message.message_type not in supported_types:
            logger.debug(f"Skipping unsupported message type: {message.message_type}")
            return

        if message.message_type == TelegramMessageType.TEXT and not message.text:
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

            # 5. Authenticated - load student record
            student_id = auth_result.student_id
            student_repo = self._student_repo or StudentRepository(session)
            student = await student_repo.get_or_create(student_id)

            # 6. Handle media message (timetable PDF / photo)
            if message.message_type in (
                TelegramMessageType.DOCUMENT,
                TelegramMessageType.PHOTO,
            ):
                await self._handle_media_message(
                    message=message,
                    session=session,
                    student_id=student_id,
                    student=student,
                )
                await self._mark_processed(idempotency_key)
                return

            # 7. Authenticated text message - load profile with timetable state
            confirmed_tt = None
            pending_tt = None
            needs_batch = False
            timetable_service = None
            attendance_service = None
            try:
                timetable_service = TimetableService(session)
                if self._student_repo:
                    timetable_service.student_repo = self._student_repo
                attendance_service = AttendanceService(session)
                confirmed_tt = await timetable_service.get_confirmed_timetable(
                    student_id
                )
                pending_tt = await timetable_service.get_pending_timetable(student_id)
                needs_batch = await timetable_service.needs_lab_batch(student_id)
            except Exception as e:
                logger.debug(
                    "Could not query timetable status for student %s: %s",
                    student_id,
                    e,
                )

            profile = self._create_student_profile(
                student,
                confirmed_tt=confirmed_tt,
                pending_tt=pending_tt,
                needs_batch=needs_batch,
            )
            student_context = self._create_student_context(student_id, profile)

            # 8. Execute conversation pipeline
            if self._conversation_service is not None:
                conversation_service = self._conversation_service
            else:
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
            try:
                response, updated_context = await conversation_service.process_message(
                    student_context, message.text or ""
                )
                if (
                    updated_context is not None
                    and hasattr(updated_context, "conversation")
                ):
                    self._conversation_contexts[
                        student_id
                    ] = updated_context.conversation
                await session.commit()
                logger.info(
                    "Generated response for student_id=%s: %r...",
                    student_id,
                    response[:60],
                )
                await self._send_response(message.chat_id, response)
            except Exception as e:
                logger.exception("Error processing conversation message: %s", e)
                fallback_msg = (
                    "Sorry, I ran into a momentary issue processing that. "
                    "Could you please send it again?"
                )
                await self._send_response(message.chat_id, fallback_msg)

        # 9. Mark as processed (idempotency)
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
            commit_fn = getattr(session, "commit", None)
            if callable(commit_fn):
                import inspect

                res = commit_fn()
                if inspect.isawaitable(res):
                    await res

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

    def _create_student_profile(
        self,
        student: Student,
        confirmed_tt: Any | None = None,
        pending_tt: Any | None = None,
        needs_batch: bool = False,
    ) -> StudentProfile:
        """Create a student profile from Student model with timetable status."""
        has_tt = isinstance(confirmed_tt, Timetable)
        if has_tt:
            tt_status = "confirmed"
        elif isinstance(pending_tt, Timetable):
            tt_status = "review_required"
        else:
            tt_status = "none"

        lab_batch_val = None
        if hasattr(student, "lab_batch") and student.lab_batch:
            lab_batch_val = getattr(student.lab_batch, "value", str(student.lab_batch))

        return StudentProfile(
            student_id=student.id,
            name=student.name,
            attendance_target=student.attendance_target,
            briefing_time=student.briefing_time,
            timezone=student.timezone or "Asia/Kolkata",
            has_timetable=has_tt,
            timetable_status=tt_status,
            lab_batch=lab_batch_val,
            needs_lab_batch=bool(needs_batch is True),
            academic_year=confirmed_tt.academic_year if has_tt else None,
            semester=confirmed_tt.semester if has_tt else None,
            branch=confirmed_tt.branch if has_tt else None,
        )

    def _create_student_context(
        self, student_id: UUID, profile: StudentProfile
    ) -> StudentContext:
        """Create or retrieve a StudentContext with persistent conversation history."""
        existing_conv = self._conversation_contexts.get(student_id)
        if existing_conv is None:
            existing_conv = ConversationContext(student_id=student_id)

        return StudentContext(
            student_id=student_id,
            profile=profile,
            conversation=existing_conv,
        )

    async def _handle_media_message(
        self,
        message: IncomingTelegramMessage,
        session: Any,
        student_id: UUID,
        student: Student,
    ) -> None:
        """Handle incoming document or photo attachment (e.g. timetable)."""
        attachment = message.attachment
        if not attachment or not attachment.file_id:
            logger.warning("Media message received without attachment or file_id")
            await self._send_response(
                message.chat_id,
                "I couldn't access that media file. Please try uploading again.",
            )
            return

        is_photo = message.message_type == TelegramMessageType.PHOTO
        orig_filename = attachment.file_name or (
            "timetable.jpg" if is_photo else "timetable.pdf"
        )
        file_ext = (
            os.path.splitext(orig_filename)[1].lower()
            or (".jpg" if is_photo else ".pdf")
        )

        storage_dir = os.path.join("storage", "timetables")
        os.makedirs(storage_dir, exist_ok=True)
        unique_suffix = attachment.file_unique_id or str(
            int(datetime.now(UTC).timestamp())
        )
        safe_name = f"{student_id}_{unique_suffix}{file_ext}"
        dest_path = os.path.join(storage_dir, safe_name)

        try:
            await self._adapter.download_file(attachment.file_id, dest_path)
        except Exception as e:
            logger.exception("Failed to download media file from Telegram: %s", e)
            await self._send_response(
                message.chat_id,
                "Sorry, I had trouble downloading your file from Telegram. "
                "Please try again in a moment.",
            )
            return

        if file_ext == ".pdf":
            await self._send_response(
                message.chat_id,
                "📥 Received your timetable PDF! "
                "Analyzing layout and extracting schedule...",
            )
            timetable_service = TimetableService(session)
            try:
                timetable = await timetable_service.create_uploaded_timetable(
                    student_id=student_id,
                    file_path=dest_path,
                    original_filename=orig_filename,
                )
                commit_fn = getattr(session, "commit", None)
                if callable(commit_fn):
                    import inspect

                    res = commit_fn()
                    if inspect.isawaitable(res):
                        await res

                if timetable.status == TimetableStatus.FAILED:
                    await self._send_response(
                        message.chat_id,
                        "❌ I couldn't extract timetable entries from this PDF. "
                        "Please verify that this is an official college circular.",
                    )
                elif timetable.status == TimetableStatus.REVIEW_REQUIRED:
                    needs_batch = await timetable_service.needs_lab_batch(student_id)
                    entries = await timetable_service.entry_repo.get_for_timetable(
                        timetable.id
                    )
                    sem_str = (
                        f"Semester {timetable.semester}"
                        if timetable.semester
                        else "Current Semester"
                    )
                    branch_str = f" - {timetable.branch}" if timetable.branch else ""
                    if needs_batch:
                        reply = (
                            f"📋 Timetable Extracted ({len(entries)} classes)\n"
                            f"Program: {sem_str}{branch_str}\n\n"
                            "⚠️ Slash-separated lab sessions detected "
                            "(Batch 1 / Batch 2).\n"
                            "Which lab batch are you in? "
                            "Please reply with Batch 1 or Batch 2."
                        )
                    else:
                        reply = (
                            f"📋 Timetable Extracted ({len(entries)} classes)\n"
                            f"Program: {sem_str}{branch_str}\n\n"
                            "Everything looks clean! "
                            "Please reply with Confirm timetable to activate it."
                        )
                    await self._send_response(message.chat_id, reply)
                elif timetable.status == TimetableStatus.CONFIRMED:
                    entries = await timetable_service.entry_repo.get_for_timetable(
                        timetable.id
                    )
                    await self._send_response(
                        message.chat_id,
                        f"✅ Timetable confirmed ({len(entries)} classes)!\n"
                        "You'll get daily morning briefings automatically.",
                    )
            except Exception as e:
                logger.exception("Error processing timetable PDF: %s", e)
                await self._send_response(
                    message.chat_id,
                    f"Encountered an issue processing timetable: {e!s}",
                )
        else:
            await self._send_response(
                message.chat_id,
                "📸 Received your timetable photo!\n\n"
                "To ensure 100% accurate extraction of multi-period lab blocks "
                "and rooms, please send the official timetable PDF document.\n\n"
                "If you only have this photo, you can type your schedule or send "
                "the PDF file whenever available.",
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
