"""
Briefing Scheduler Worker — Personal Alpha.

Proactively sends daily morning briefings to eligible students via Telegram
at their configured briefing time in their local timezone.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app.telegram.models import OutgoingTelegramMessage, TelegramContactIdentity

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.student import Student
    from app.models.telegram_identity import TelegramIdentity
    from app.telegram.bot_adapter import TelegramBotAdapter

logger = logging.getLogger(__name__)

DEFAULT_BRIEFING_TIME = "08:30"
DEFAULT_TIMEZONE = "Asia/Kolkata"
SCHEDULER_INTERVAL_SECONDS = 60


class BriefingScheduler:
    """
    Background worker that sends daily morning briefings to eligible students.

    Runs periodically and checks for students whose briefing time has arrived
    in their local timezone. Uses idempotent delivery tracking to prevent
    duplicate sends.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        telegram_adapter: TelegramBotAdapter,
        *,
        interval_seconds: int = SCHEDULER_INTERVAL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._telegram_adapter = telegram_adapter
        self._interval = interval_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Briefing scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Briefing scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._process_due_briefings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in briefing scheduler loop: %s", e)
            await asyncio.sleep(self._interval)

    async def _process_due_briefings(self) -> None:
        """Find and process students whose briefing time has arrived."""
        now_utc = self._now()

        # Get all active students with active telegram identities
        async with self._session_factory() as session:
            from app.repositories.student import StudentRepository
            from app.repositories.telegram_identity import TelegramIdentityRepository

            student_repo = StudentRepository(session)
            telegram_repo = TelegramIdentityRepository(session)

            # Get all active students
            students = await student_repo.get_active_students()
            if not students:
                return

            # Build a list of eligible students with their telegram identities
            eligible_students = []
            for student in students:
                identities = await telegram_repo.get_active_for_student(student.id)
                if identities:
                    eligible_students.append((student, identities[0]))

        # Process each eligible student
        for student, telegram_identity in eligible_students:
            await self._try_deliver_briefing(student, telegram_identity, now_utc)

    async def _try_deliver_briefing(
        self,
        student: Student,
        telegram_identity: TelegramIdentity,
        now_utc: datetime,
    ) -> None:
        """Attempt to deliver briefing for one student."""
        async with self._session_factory() as session:
            from app.intelligence.models.context import StudentProfile
            from app.intelligence.services.attendance_service import AttendanceService
            from app.intelligence.services.briefing import create_briefing_service
            from app.intelligence.services.context_builder import create_student_context
            from app.intelligence.services.timetable_service import TimetableService
            from app.repositories.briefing_delivery import BriefingDeliveryRepository

            delivery_repo = BriefingDeliveryRepository(session)

            # Get student's timezone and briefing time
            briefing_time_str = student.briefing_time or DEFAULT_BRIEFING_TIME
            try:
                briefing_time = time.fromisoformat(briefing_time_str)
            except ValueError:
                logger.warning(
                    "Invalid briefing_time for student %s: %s, using default",
                    student.id,
                    briefing_time_str,
                )
                briefing_time = time.fromisoformat(DEFAULT_BRIEFING_TIME)

            student_tz = student.timezone or DEFAULT_TIMEZONE
            try:
                tz = ZoneInfo(student_tz)
            except Exception:
                logger.warning(
                    "Invalid timezone for student %s: %s, using default",
                    student.id,
                    student_tz,
                )
                tz = ZoneInfo(DEFAULT_TIMEZONE)

            # Calculate local date and check if briefing time has passed
            local_now = now_utc.astimezone(tz)
            local_date = local_now.date()
            scheduled_local = datetime.combine(local_date, briefing_time, tzinfo=tz)
            scheduled_utc = scheduled_local.astimezone(UTC)

            if local_now < scheduled_local:
                # Not time yet
                return

            # Create delivery record (idempotent)
            delivery = await delivery_repo.create_pending(
                student_id=student.id,
                telegram_identity_id=telegram_identity.id,
                delivery_date=local_date,
                scheduled_at=scheduled_utc,
            )
            if not delivery:
                # Already exists (race condition or already sent)
                return

            try:
                # Build StudentProfile from persisted Student model fields
                profile = StudentProfile(
                    student_id=student.id,
                    name=student.name,
                    briefing_time=student.briefing_time,
                    timezone=student.timezone,
                    attendance_target=student.attendance_target,
                )
                context = create_student_context(student.id, profile=profile)

                # Generate briefing
                timetable_service = TimetableService(session)
                attendance_service = AttendanceService(session)
                briefing_service = create_briefing_service(
                    timetable_service, attendance_service
                )
                result = await briefing_service.generate_briefing(context)

                # Send via Telegram
                bot_identity = await self._telegram_adapter.get_our_identity()
                if not bot_identity:
                    raise RuntimeError("Telegram bot identity not available")

                message = OutgoingTelegramMessage(
                    to_contact=TelegramContactIdentity(
                        provider=telegram_identity.provider,
                        provider_user_id=telegram_identity.provider_user_id,
                        normalized_identifier=telegram_identity.normalized_identifier,
                    ),
                    from_contact=bot_identity,
                    message_type="text",
                    chat_id=telegram_identity.provider_user_id,
                    text=result.message,
                )

                await self._telegram_adapter.send_message(message)

                # Mark as sent
                await delivery_repo.mark_sent(delivery.id, datetime.now(UTC))
                await self._commit_session(session)
                logger.info("Delivered briefing to student %s", student.id)

            except Exception as e:
                logger.exception(
                    "Failed to deliver briefing to student %s: %s",
                    student.id,
                    e,
                )
                await delivery_repo.mark_failed(
                    delivery.id, str(e), delivery.attempt_count + 1
                )
                await self._commit_session(session)

    async def _commit_session(self, session: Any) -> None:
        """Safely commit session if commit method exists and is awaitable."""
        import inspect

        commit_fn = getattr(session, "commit", None)
        if callable(commit_fn):
            res = commit_fn()
            if inspect.isawaitable(res):
                await res


def create_briefing_scheduler(
    session_factory: Callable[[], Any],
    telegram_adapter: TelegramBotAdapter,
    *,
    interval_seconds: int = SCHEDULER_INTERVAL_SECONDS,
) -> BriefingScheduler:
    """Factory for BriefingScheduler."""
    return BriefingScheduler(
        session_factory=session_factory,
        telegram_adapter=telegram_adapter,
        interval_seconds=interval_seconds,
    )
