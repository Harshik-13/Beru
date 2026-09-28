"""add_telegram_linking_challenge

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6
Create Date: 2026-09-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    telegram_linking_challenge_status = postgresql.ENUM(
        "pending",
        "used",
        "expired",
        name="telegram_linking_challenge_status",
        create_type=True,
    )
    telegram_linking_challenge_status.create(op.get_bind(), checkfirst=True)

    # Create telegram_linking_challenges table
    op.create_table(
        "telegram_linking_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("telegram_user_id", sa.String(255), nullable=False),
        sa.Column("challenge_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "used", "expired", name="telegram_linking_challenge_status", create_type=False), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_identity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["telegram_identity_id"],
            ["telegram_identities.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes and constraints
    op.create_index(
        "ix_telegram_linking_challenges_telegram_user_id",
        "telegram_linking_challenges",
        ["telegram_user_id"],
    )
    op.create_index(
        "ix_telegram_linking_challenges_student_id",
        "telegram_linking_challenges",
        ["student_id"],
    )
    op.create_index(
        "ix_telegram_linking_challenges_expires_at",
        "telegram_linking_challenges",
        ["expires_at"],
    )
    op.create_index(
        "ix_telegram_linking_challenges_status",
        "telegram_linking_challenges",
        ["status"],
    )
    op.create_unique_constraint(
        "uq_telegram_linking_challenge_token",
        "telegram_linking_challenges",
        ["challenge_token"],
    )

    # Add new audit event types (handled by enum auto-creation in PostgreSQL)
    # The enum values are added automatically when the enum is used


def downgrade() -> None:
    op.drop_constraint("uq_telegram_linking_challenge_token", "telegram_linking_challenges", type_="unique")
    op.drop_index("ix_telegram_linking_challenges_status", table_name="telegram_linking_challenges")
    op.drop_index("ix_telegram_linking_challenges_expires_at", table_name="telegram_linking_challenges")
    op.drop_index("ix_telegram_linking_challenges_student_id", table_name="telegram_linking_challenges")
    op.drop_index("ix_telegram_linking_challenges_telegram_user_id", table_name="telegram_linking_challenges")
    op.drop_table("telegram_linking_challenges")

    op.execute("DROP TYPE IF EXISTS telegram_linking_challenge_status")