"""initial migration: students and whatsapp_identities

Revision ID: 5d414855ae22
Revises:
Create Date: 2026-09-25 18:54:25.158804
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '5d414855ae22'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # students table
    op.create_table(
        "students",
        sa.Column("status", sa.String(length=8), nullable=False, server_default="active"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_students"),
    )

    # whatsapp_identities table
    op.create_table(
        "whatsapp_identities",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=15), nullable=False, server_default="unknown"),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("normalized_identifier", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="active"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_whatsapp_identities"),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_whatsapp_identities_student_id_students",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_whatsapp_identity_provider_user"),
    )

    op.create_index(
        "ix_whatsapp_identities_student_id",
        "whatsapp_identities",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "ix_whatsapp_identities_normalized_identifier",
        "whatsapp_identities",
        ["normalized_identifier"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_identities_normalized_identifier", table_name="whatsapp_identities")
    op.drop_index("ix_whatsapp_identities_student_id", table_name="whatsapp_identities")
    op.drop_table("whatsapp_identities")
    op.drop_table("students")