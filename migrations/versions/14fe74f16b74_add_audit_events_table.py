"""add audit_events table

Revision ID: 14fe74f16b74
Revises: 5d414855ae22
Create Date: 2026-09-25 19:16:56.011304
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '14fe74f16b74'
down_revision: Union[str, None] = '5d414855ae22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # audit_events table
    op.create_table(
        "audit_events",
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("external_identity_id", sa.String(length=255), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_audit_events_student_id_students",
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_audit_events_student_id_created_at",
        "audit_events",
        ["student_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_event_type_created_at",
        "audit_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_event_type_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_student_id_created_at", table_name="audit_events")
    op.drop_table("audit_events")