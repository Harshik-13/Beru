import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student


class AuditEventType(str, enum.Enum):  # noqa: UP042
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHENTICATION_FAILURE = "authentication_failure"
    IDENTITY_DISABLED = "identity_disabled"
    IDENTITY_REVOKED = "identity_revoked"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    AUTHORIZATION_FAILURE = "authorization_failure"
    STUDENT_CREATED = "student_created"
    STUDENT_UPDATED = "student_updated"
    WHATSAPP_IDENTITY_CREATED = "whatsapp_identity_created"
    WHATSAPP_IDENTITY_UPDATED = "whatsapp_identity_updated"
    TELEGRAM_IDENTITY_LINKED = "telegram_identity_linked"
    TELEGRAM_IDENTITY_LINK_FAILED = "telegram_identity_link_failed"


class AuditEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_events"

    event_type: Mapped[AuditEventType] = mapped_column(
        SQLEnum(AuditEventType, name="audit_event_type", native_enum=False),
        nullable=False,
    )

    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    external_identity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    success: Mapped[bool] = mapped_column(nullable=False, default=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped["Student"] = relationship("Student", lazy="selectin")

    __table_args__ = (
        Index("ix_audit_events_student_id_created_at", "student_id", "created_at"),
        Index("ix_audit_events_event_type_created_at", "event_type", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEvent(id={self.id}, type={self.event_type}, "
            f"student_id={self.student_id}, success={self.success})>"
        )
