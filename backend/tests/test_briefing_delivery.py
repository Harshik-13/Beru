"""Focused BriefingDelivery repository/model tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.briefing_delivery import (
    BriefingDelivery,
    BriefingDeliveryStatus,
)
from app.repositories.briefing_delivery import BriefingDeliveryRepository


class TestBriefingDeliveryModel:
    """Test BriefingDelivery model creation and validation."""

    def test_delivery_creation_minimal(self):
        """Test creating a delivery with required fields."""
        student_id = uuid4()
        telegram_identity_id = uuid4()
        delivery = BriefingDelivery(
            student_id=student_id,
            telegram_identity_id=telegram_identity_id,
            delivery_date=date(2026, 9, 28),
            scheduled_at=datetime.now(UTC),
        )

        assert delivery.student_id == student_id
        assert delivery.telegram_identity_id == telegram_identity_id
        assert delivery.delivery_date == date(2026, 9, 28)
        # status/attempt_count defaults are applied at INSERT time by SQLAlchemy
        assert delivery.sent_at is None
        assert delivery.error_message is None

    def test_delivery_status_enum_values(self):
        """Test all status enum values are valid."""
        assert BriefingDeliveryStatus.PENDING == "pending"
        assert BriefingDeliveryStatus.SENT == "sent"
        assert BriefingDeliveryStatus.FAILED == "failed"


class TestBriefingDeliveryRepository:
    """Test BriefingDeliveryRepository operations."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return BriefingDeliveryRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_pending_new_delivery(self, repo, mock_session):
        """Test creating a new pending delivery."""
        student_id = uuid4()
        telegram_identity_id = uuid4()
        delivery_date = date(2026, 9, 28)
        scheduled_at = datetime.now(UTC)

        # Mock no existing delivery
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        delivery = await repo.create_pending(
            student_id=student_id,
            telegram_identity_id=telegram_identity_id,
            delivery_date=delivery_date,
            scheduled_at=scheduled_at,
        )

        assert delivery is not None
        assert delivery.student_id == student_id
        assert delivery.telegram_identity_id == telegram_identity_id
        assert delivery.delivery_date == delivery_date
        assert delivery.scheduled_at == scheduled_at
        assert delivery.status == BriefingDeliveryStatus.PENDING
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_pending_idempotent_returns_none(self, repo, mock_session):
        """Test create_pending returns None when delivery already exists."""
        student_id = uuid4()
        telegram_identity_id = uuid4()
        delivery_date = date(2026, 9, 28)
        scheduled_at = datetime.now(UTC)

        # Mock existing delivery
        existing = BriefingDelivery(
            student_id=student_id,
            telegram_identity_id=telegram_identity_id,
            delivery_date=delivery_date,
            scheduled_at=scheduled_at,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        delivery = await repo.create_pending(
            student_id=student_id,
            telegram_identity_id=telegram_identity_id,
            delivery_date=delivery_date,
            scheduled_at=scheduled_at,
        )

        assert delivery is None
        mock_session.add.assert_not_called()
        mock_session.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_by_student_and_date(self, repo, mock_session):
        """Test getting delivery by student and date."""
        student_id = uuid4()
        delivery_date = date(2026, 9, 28)
        delivery = BriefingDelivery(
            student_id=student_id,
            telegram_identity_id=uuid4(),
            delivery_date=delivery_date,
            scheduled_at=datetime.now(UTC),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = delivery
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_student_and_date(student_id, delivery_date)

        assert result == delivery
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_pending_for_date(self, repo, mock_session):
        """Test getting all pending deliveries for a date."""
        delivery_date = date(2026, 9, 28)
        deliveries = [
            BriefingDelivery(
                student_id=uuid4(),
                telegram_identity_id=uuid4(),
                delivery_date=delivery_date,
                scheduled_at=datetime.now(UTC),
            )
            for _ in range(2)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = deliveries
        mock_session.execute.return_value = mock_result

        result = await repo.get_pending_for_date(delivery_date)

        assert result == deliveries
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_sent(self, repo, mock_session):
        """Test marking a delivery as sent."""
        delivery_id = uuid4()
        delivery = BriefingDelivery(
            id=delivery_id,
            student_id=uuid4(),
            telegram_identity_id=uuid4(),
            delivery_date=date(2026, 9, 28),
            scheduled_at=datetime.now(UTC),
            status=BriefingDeliveryStatus.PENDING,
            attempt_count=0,
        )
        sent_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = delivery
        mock_session.execute.return_value = mock_result

        result = await repo.mark_sent(delivery_id, sent_at)

        assert result is not None
        assert result.status == BriefingDeliveryStatus.SENT
        assert result.sent_at == sent_at
        assert result.attempt_count == 1
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_failed(self, repo, mock_session):
        """Test marking a delivery as failed."""
        delivery_id = uuid4()
        delivery = BriefingDelivery(
            id=delivery_id,
            student_id=uuid4(),
            telegram_identity_id=uuid4(),
            delivery_date=date(2026, 9, 28),
            scheduled_at=datetime.now(UTC),
            status=BriefingDeliveryStatus.PENDING,
            attempt_count=1,
        )
        error = "Telegram API timeout"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = delivery
        mock_session.execute.return_value = mock_result

        result = await repo.mark_failed(delivery_id, error, 2)

        assert result is not None
        assert result.status == BriefingDeliveryStatus.FAILED
        assert result.error_message == error
        assert result.attempt_count == 2
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_increment_attempt(self, repo, mock_session):
        """Test incrementing attempt count for retry."""
        delivery_id = uuid4()
        delivery = BriefingDelivery(
            id=delivery_id,
            student_id=uuid4(),
            telegram_identity_id=uuid4(),
            delivery_date=date(2026, 9, 28),
            scheduled_at=datetime.now(UTC),
            status=BriefingDeliveryStatus.FAILED,
            attempt_count=2,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = delivery
        mock_session.execute.return_value = mock_result

        result = await repo.increment_attempt(delivery_id)

        assert result is not None
        assert result.attempt_count == 3
        assert result.status == BriefingDeliveryStatus.PENDING
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_operations_return_none_when_not_found(self, repo, mock_session):
        """Test all operations return None when delivery not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        assert await repo.mark_sent(uuid4(), datetime.now(UTC)) is None
        assert await repo.mark_failed(uuid4(), "error", 1) is None
        assert await repo.increment_attempt(uuid4()) is None
