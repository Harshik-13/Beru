"""
Portal credential model for secure encrypted storage.
"""

import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PortalCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted portal credential storage."""

    __tablename__ = "portal_credentials"

    student_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    portal: Mapped[str] = mapped_column(String(50), nullable=False)

    roll_number: Mapped[str] = mapped_column(String(100), nullable=False)

    encrypted_password: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "portal",
            name="uq_portal_credential_student_portal",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PortalCredential(id={self.id}, "
            f"student_id={self.student_id}, portal={self.portal})>"
        )
