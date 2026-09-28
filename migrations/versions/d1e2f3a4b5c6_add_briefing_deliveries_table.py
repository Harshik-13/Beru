"""add_briefing_deliveries_table

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-09-28 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type
    briefing_delivery_status = postgresql.ENUM(
        "pending",
        "sent",
        "failed",
        name="briefing_delivery_status",
        create_type=True,
    )
    briefing_delivery_status.create(op.get_bind(), checkfirst=True)

    # Create briefing_deliveries table
    op.create_table(
        "briefing_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "sent", "failed", name="briefing_delivery_status", create_type=False), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["telegram_identity_id"],
            ["telegram_identities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes and constraints
    op.create_index(
        "ix_briefing_deliveries_student_id",
        "briefing_deliveries",
        ["student_id"],
    )
    op.create_index(
        "ix_briefing_deliveries_delivery_date",
        "briefing_deliveries",
        ["delivery_date"],
    )
    op.create_index(
        "ix_briefing_deliveries_status",
        "briefing_deliveries",
        ["status"],
    )
    op.create_unique_constraint(
        "uq_briefing_delivery_student_date",
        "briefing_deliveries",
        ["student_id", "delivery_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_briefing_delivery_student_date", "briefing_deliveries", type_="unique")
    op.drop_index("ix_briefing_deliveries_status", table_name="briefing_deliveries")
    op.drop_index("ix_briefing_deliveries_delivery_date", table_name="briefing_deliveries")
    op.drop_index("ix_briefing_deliveries_student_id", table_name="briefing_deliveries")
    op.drop_table("briefing_deliveries")

    op.execute("DROP TYPE IF EXISTS briefing_delivery_status")