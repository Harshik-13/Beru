import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student


class TelegramLinkingChallengeStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"


class TelegramLinkingChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Stores a single-use linking challenge for Telegram identity verification."""

    __tablename__ = "telegram_linking_challenges"

    telegram_user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    challenge_token: Mapped[str] = mapped_column(String(64), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped["TelegramLinkingChallengeStatus"] = mapped_column(
        SQLEnum(
            TelegramLinkingChallengeStatus,
            name="telegram_linking_challenge_status",
            native_enum=False,
        ),
        default=TelegramLinkingChallengeStatus.PENDING,
        nullable=False,
    )

    # Only set when challenge is used
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
    )

    telegram_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_identities.id", ondelete="SET NULL"),
        nullable=True,
    )

    student: Mapped["Student | None"] = relationship("Student", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "challenge_token",
            name="uq_telegram_linking_challenge_token",
        ),
        Index("ix_telegram_linking_challenges_telegram_user_id", "telegram_user_id"),
        Index("ix_telegram_linking_challenges_student_id", "student_id"),
        Index("ix_telegram_linking_challenges_expires_at", "expires_at"),
        Index("ix_telegram_linking_challenges_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramLinkingChallenge(id={self.id}, "
            f"telegram_user_id={self.telegram_user_id}, "
            f"status={self.status})>"
        )
