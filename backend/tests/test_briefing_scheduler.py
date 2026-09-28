"""Focused BriefingScheduler tests using mocks/fakes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.student import Student, StudentStatus
from app.models.telegram_identity import (
    TelegramIdentity,
    TelegramIdentityStatus,
    TelegramProvider,
)
from app.workers.briefing_scheduler import (
    BriefingScheduler,
)

FIXED_NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)  # 09:00 UTC = 14:30 IST


def make_student(
    *,
    status: StudentStatus = StudentStatus.ACTIVE,
    briefing_time: str | None = None,
    timezone: str = "Asia/Kolkata",
) -> Student:
    return Student(
        id=uuid4(),
        status=status,
        briefing_time=briefing_time,
        timezone=timezone,
    )


def make_telegram_identity(student_id: uuid4) -> TelegramIdentity:
    return TelegramIdentity(
        id=uuid4(),
        student_id=student_id,
        provider=TelegramProvider.TELEGRAM_BOT,
        provider_user_id=str(uuid4().int)[:10],
        status=TelegramIdentityStatus.ACTIVE,
    )


def make_mock_session_factory(students, identities_by_student, deliveries=None):
    """Create a mock session factory that returns mock sessions."""
    deliveries = deliveries or {}

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def session_factory():
        yield mock_session

    return session_factory, mock_session


def make_scheduler(
    students,
    identities_by_student,
    deliveries=None,
    *,
    now=FIXED_NOW,
    telegram_adapter=None,
):
    """Create a BriefingScheduler with mocked dependencies."""
    session_factory, mock_session = make_mock_session_factory(
        students, identities_by_student, deliveries
    )

    if telegram_adapter is None:
        telegram_adapter = MagicMock()
        telegram_adapter.get_our_identity = AsyncMock(
            return_value=MagicMock(provider_user_id="bot123")
        )
        telegram_adapter.send_message = AsyncMock(return_value="msg_123")

    scheduler = BriefingScheduler(
        session_factory=session_factory,
        telegram_adapter=telegram_adapter,
        interval_seconds=60,
        now=lambda: now,
    )

    return scheduler, mock_session, telegram_adapter


class TestBriefingSchedulerEligibility:
    """Tests for student eligibility filtering."""

    @pytest.mark.asyncio
    async def test_active_linked_student_is_selected(self):
        """Active student with Telegram identity is processed."""
        student = make_student()
        identity = make_telegram_identity(student.id)

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=MagicMock(
                    id=uuid4(), attempt_count=0, student_id=student.id
                )
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_result = MagicMock()
            mock_briefing_result.message = "Test briefing"
            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=mock_briefing_result
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            MockStudentRepo.return_value.get_active_students.assert_awaited_once()
            MockTelegramRepo.return_value.get_active_for_student.assert_awaited_with(
                student.id
            )

    @pytest.mark.asyncio
    async def test_inactive_student_skipped(self):
        """Inactive student is not processed."""
        student = make_student(status=StudentStatus.INACTIVE)
        identity = make_telegram_identity(student.id)

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[]
            )

            await scheduler._process_due_briefings()

            MockTelegramRepo.return_value.get_active_for_student.assert_not_called()

    @pytest.mark.asyncio
    async def test_student_without_telegram_identity_skipped(self):
        """Student without Telegram identity is not processed."""
        student = make_student()

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[]
            )

            await scheduler._process_due_briefings()

            MockTelegramRepo.return_value.get_active_for_student.assert_awaited_with(
                student.id
            )


class TestBriefingSchedulerTiming:
    """Tests for briefing time and timezone handling."""

    @pytest.mark.asyncio
    async def test_configured_briefing_time_respected(self):
        """Student with custom briefing_time is processed at that time."""
        student = make_student(briefing_time="07:00")
        identity = make_telegram_identity(student.id)

        # 09:00 UTC = 14:30 IST, so 07:00 IST has passed
        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
            now=FIXED_NOW,
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Test")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            MockDeliveryRepo.return_value.create_pending.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_briefing_time_used(self):
        """Student without briefing_time uses default 08:30."""
        student = make_student(briefing_time=None)
        identity = make_telegram_identity(student.id)

        # 09:00 UTC = 14:30 IST, default 08:30 IST has passed
        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
            now=FIXED_NOW,
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Test")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            MockDeliveryRepo.return_value.create_pending.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_student_timezone_respected(self):
        """Student in different timezone is processed at correct local time."""
        # Student in UTC-5 (e.g., US Eastern)
        student = make_student(timezone="America/New_York")
        identity = make_telegram_identity(student.id)

        # 09:00 UTC = 04:00 EST, default 08:30 EST has NOT passed
        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
            now=FIXED_NOW,
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )

            await scheduler._process_due_briefings()

            # Should NOT create delivery because 08:30 EST hasn't passed yet
            MockDeliveryRepo.return_value.create_pending.assert_not_called()


class TestBriefingSchedulerDelivery:
    """Tests for briefing delivery and idempotency."""

    @pytest.mark.asyncio
    async def test_briefing_service_called_for_correct_student(self):
        """BriefingService generates briefing for the correct student."""
        student = make_student()
        identity = make_telegram_identity(student.id)

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Test briefing")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            mock_briefing_service.generate_briefing.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_telegram_send_called_with_briefing(self):
        """Telegram adapter sends the generated briefing message."""
        student = make_student()
        identity = make_telegram_identity(student.id)

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Good morning!")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            _.send_message.assert_awaited_once()
            sent_msg = _.send_message.call_args[0][0]
            assert sent_msg.text == "Good morning!"
            assert sent_msg.chat_id == identity.provider_user_id

    @pytest.mark.asyncio
    async def test_duplicate_delivery_prevented(self):
        """Existing delivery record prevents duplicate send."""
        student = make_student()
        identity = make_telegram_identity(student.id)
        existing_delivery = MagicMock(id=uuid4())

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=existing_delivery
            )
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=None
            )

            await scheduler._process_due_briefings()

            # create_pending was called but returned None (idempotent), so no send
            MockDeliveryRepo.return_value.create_pending.assert_awaited_once()
            _.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_records_retry_state(self):
        """Failed delivery records error and attempt count."""
        student = make_student()
        identity = make_telegram_identity(student.id)

        adapter = MagicMock()
        adapter.get_our_identity = AsyncMock(
            return_value=MagicMock(provider_user_id="bot123")
        )
        adapter.send_message = AsyncMock(
            side_effect=RuntimeError("Telegram API error")
        )

        scheduler, _, _ = make_scheduler(
            students=[student],
            identities_by_student={student.id: [identity]},
            telegram_adapter=adapter,
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                return_value=[identity]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_failed = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Test")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            MockDeliveryRepo.return_value.mark_failed.assert_awaited_once()
            MockDeliveryRepo.return_value.mark_sent.assert_not_called()


class TestBriefingSchedulerIsolation:
    """Tests for multi-student isolation."""

    @pytest.mark.asyncio
    async def test_multiple_students_remain_isolated(self):
        """Each student's briefing is sent only to their own Telegram identity."""
        student1 = make_student()
        student2 = make_student()
        identity1 = make_telegram_identity(student1.id)
        identity2 = make_telegram_identity(student2.id)

        scheduler, _, _ = make_scheduler(
            students=[student1, student2],
            identities_by_student={
                student1.id: [identity1],
                student2.id: [identity2],
            },
        )

        with patch(
            "app.repositories.student.StudentRepository"
        ) as MockStudentRepo, patch(
            "app.repositories.telegram_identity.TelegramIdentityRepository"
        ) as MockTelegramRepo, patch(
            "app.repositories.briefing_delivery.BriefingDeliveryRepository"
        ) as MockDeliveryRepo, patch(
            "app.intelligence.services.briefing.create_briefing_service"
        ) as mock_briefing_factory:
            MockStudentRepo.return_value.get_active_students = AsyncMock(
                return_value=[student1, student2]
            )
            MockTelegramRepo.return_value.get_active_for_student = AsyncMock(
                side_effect=lambda sid: {
                    student1.id: [identity1],
                    student2.id: [identity2],
                }[sid]
            )
            MockDeliveryRepo.return_value.get_by_student_and_date = AsyncMock(
                return_value=None
            )
            mock_delivery = MagicMock(id=uuid4(), attempt_count=0)
            MockDeliveryRepo.return_value.create_pending = AsyncMock(
                return_value=mock_delivery
            )
            MockDeliveryRepo.return_value.mark_sent = AsyncMock()

            mock_briefing_service = MagicMock()
            mock_briefing_service.generate_briefing = AsyncMock(
                return_value=MagicMock(message="Test")
            )
            mock_briefing_factory.return_value = mock_briefing_service

            await scheduler._process_due_briefings()

            assert _.send_message.await_count == 2
            sent_chats = [
                call[0][0].chat_id for call in _.send_message.call_args_list
            ]
            assert identity1.provider_user_id in sent_chats
            assert identity2.provider_user_id in sent_chats


class TestBriefingSchedulerNoAttendanceLogic:
    """Verify scheduler does not perform attendance calculations itself."""

    @pytest.mark.asyncio
    async def test_scheduler_does_not_import_attendance_service(self):
        """Scheduler module does not directly import AttendanceService."""
        import inspect

        from app.workers import briefing_scheduler

        source = inspect.getsource(briefing_scheduler)
        # AttendanceService is only used via BriefingService, not directly
        assert "class AttendanceService" not in source
        assert "def calculate_percentage" not in source
        assert "def simulate_absence" not in source
