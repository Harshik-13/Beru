"""add_telegram_identities_table

Revision ID: a1b2c3d4e5f6
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27 20:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    telegram_provider = postgresql.ENUM(
        "telegram_bot",
        name="telegram_provider",
        create_type=True,
    )
    telegram_provider.create(op.get_bind(), checkfirst=True)

    telegram_identity_status = postgresql.ENUM(
        "active",
        "disabled",
        "revoked",
        name="telegram_identity_status",
        create_type=True,
    )
    telegram_identity_status.create(op.get_bind(), checkfirst=True)

    # Create telegram_identities table
    op.create_table(
        "telegram_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM("telegram_bot", name="telegram_provider", create_type=False), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("normalized_identifier", sa.String(255), nullable=True),
        sa.Column("status", postgresql.ENUM("active", "disabled", "revoked", name="telegram_identity_status", create_type=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes and constraints
    op.create_index(
        "ix_telegram_identities_student_id",
        "telegram_identities",
        ["student_id"],
    )
    op.create_index(
        "ix_telegram_identities_normalized_identifier",
        "telegram_identities",
        ["normalized_identifier"],
    )
    op.create_unique_constraint(
        "uq_telegram_identity_provider_user",
        "telegram_identities",
        ["provider", "provider_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_telegram_identity_provider_user", "telegram_identities", type_="unique")
    op.drop_index("ix_telegram_identities_normalized_identifier", table_name="telegram_identities")
    op.drop_index("ix_telegram_identities_student_id", table_name="telegram_identities")
    op.drop_table("telegram_identities")

    op.execute("DROP TYPE IF EXISTS telegram_identity_status")
    op.execute("DROP TYPE IF EXISTS telegram_provider")