import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student


class TelegramProvider(str, enum.Enum):  # noqa: UP042
    TELEGRAM_BOT = "telegram_bot"


class TelegramIdentityStatus(str, enum.Enum):  # noqa: UP042
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


class TelegramIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "telegram_identities"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[TelegramProvider] = mapped_column(
        SQLEnum(
            TelegramProvider,
            name="telegram_provider",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=TelegramProvider.TELEGRAM_BOT,
        nullable=False,
    )

    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    normalized_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[TelegramIdentityStatus] = mapped_column(
        SQLEnum(
            TelegramIdentityStatus,
            name="telegram_identity_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=TelegramIdentityStatus.ACTIVE,
        nullable=False,
    )

    student: Mapped["Student"] = relationship("Student", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_telegram_identity_provider_user",
        ),
        Index("ix_telegram_identities_student_id", "student_id"),
        Index("ix_telegram_identities_normalized_identifier", "normalized_identifier"),
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramIdentity(id={self.id}, "
            f"student_id={self.student_id}, "
            f"provider={self.provider})>"
        )
