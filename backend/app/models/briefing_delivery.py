"""
Briefing Delivery model — tracks morning briefing delivery attempts for idempotency.
"""

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student
    from app.models.telegram_identity import TelegramIdentity


class BriefingDeliveryStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class BriefingDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks a morning briefing delivery attempt for a student on a specific date.

    Ensures idempotency: one delivery attempt per student per local date.
    """

    __tablename__ = "briefing_deliveries"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    telegram_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_identities.id", ondelete="CASCADE"),
        nullable=False,
    )

    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[BriefingDeliveryStatus] = mapped_column(
        SQLEnum(
            BriefingDeliveryStatus,
            name="briefing_delivery_status",
            native_enum=False,
        ),
        default=BriefingDeliveryStatus.PENDING,
        nullable=False,
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(nullable=True)

    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Relationships
    student: Mapped["Student"] = relationship("Student", lazy="selectin")
    telegram_identity: Mapped["TelegramIdentity"] = relationship(
        "TelegramIdentity", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "delivery_date",
            name="uq_briefing_delivery_student_date",
        ),
        Index("ix_briefing_deliveries_student_id", "student_id"),
        Index("ix_briefing_deliveries_delivery_date", "delivery_date"),
        Index("ix_briefing_deliveries_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<BriefingDelivery(id={self.id}, student_id={self.student_id}, "
            f"date={self.delivery_date}, status={self.status})>"
        )
