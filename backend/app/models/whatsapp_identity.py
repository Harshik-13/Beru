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


class WhatsAppProvider(str, enum.Enum):  # noqa: UP042
    UNKNOWN = "unknown"
    WHATSAPP_WEB_JS = "whatsapp_web_js"
    BAILEYS = "baileys"
    META_CLOUD_API = "meta_cloud_api"


class WhatsAppIdentityStatus(str, enum.Enum):  # noqa: UP042
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


class WhatsAppIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "whatsapp_identities"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[WhatsAppProvider] = mapped_column(
        SQLEnum(WhatsAppProvider, name="whatsapp_provider", native_enum=False),
        default=WhatsAppProvider.UNKNOWN,
        nullable=False,
    )

    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    normalized_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[WhatsAppIdentityStatus] = mapped_column(
        SQLEnum(
            WhatsAppIdentityStatus,
            name="whatsapp_identity_status",
            native_enum=False,
        ),
        default=WhatsAppIdentityStatus.ACTIVE,
        nullable=False,
    )

    student: Mapped["Student"] = relationship("Student", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_whatsapp_identity_provider_user",
        ),
        Index("ix_whatsapp_identities_student_id", "student_id"),
        Index("ix_whatsapp_identities_normalized_identifier", "normalized_identifier"),
    )

    def __repr__(self) -> str:
        return (
            f"<WhatsAppIdentity(id={self.id}, "
            f"student_id={self.student_id}, "
            f"provider={self.provider})>"
        )
