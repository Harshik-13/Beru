"""
Repository for BriefingDelivery model.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.briefing_delivery import (
    BriefingDelivery,
    BriefingDeliveryStatus,
)


class BriefingDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_pending(
        self,
        *,
        student_id: UUID,
        telegram_identity_id: UUID,
        delivery_date: date,
        scheduled_at: datetime,
    ) -> BriefingDelivery | None:
        """
        Create a pending briefing delivery record.

        Returns the created record, or None if a record for the same
        student/date already exists (idempotency).
        """
        existing = await self.get_by_student_and_date(student_id, delivery_date)
        if existing:
            return None

        delivery = BriefingDelivery(
            student_id=student_id,
            telegram_identity_id=telegram_identity_id,
            delivery_date=delivery_date,
            status=BriefingDeliveryStatus.PENDING,
            scheduled_at=scheduled_at,
        )
        self._session.add(delivery)
        await self._session.flush()
        return delivery

    async def get_by_student_and_date(
        self, student_id: UUID, delivery_date: date
    ) -> BriefingDelivery | None:
        """Get delivery record for a student on a specific date."""
        result = await self._session.execute(
            select(BriefingDelivery).where(
                BriefingDelivery.student_id == student_id,
                BriefingDelivery.delivery_date == delivery_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_for_date(self, delivery_date: date) -> list[BriefingDelivery]:
        """Get all pending deliveries for a specific date."""
        result = await self._session.execute(
            select(BriefingDelivery).where(
                BriefingDelivery.delivery_date == delivery_date,
                BriefingDelivery.status == BriefingDeliveryStatus.PENDING,
            )
        )
        return list(result.scalars().all())

    async def mark_sent(
        self, delivery_id: UUID, sent_at: datetime
    ) -> BriefingDelivery | None:
        """Mark a delivery as sent."""
        result = await self._session.execute(
            select(BriefingDelivery).where(BriefingDelivery.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return None

        delivery.status = BriefingDeliveryStatus.SENT
        delivery.sent_at = sent_at
        delivery.attempt_count += 1
        await self._session.flush()
        return delivery

    async def mark_failed(
        self, delivery_id: UUID, error_message: str, attempt_count: int
    ) -> BriefingDelivery | None:
        """Mark a delivery as failed."""
        result = await self._session.execute(
            select(BriefingDelivery).where(BriefingDelivery.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return None

        delivery.status = BriefingDeliveryStatus.FAILED
        delivery.error_message = error_message
        delivery.attempt_count = attempt_count
        await self._session.flush()
        return delivery

    async def increment_attempt(self, delivery_id: UUID) -> BriefingDelivery | None:
        """Increment attempt count for retry."""
        result = await self._session.execute(
            select(BriefingDelivery).where(BriefingDelivery.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return None

        delivery.attempt_count += 1
        delivery.status = BriefingDeliveryStatus.PENDING
        await self._session.flush()
        return delivery
