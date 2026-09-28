"""add_student_briefing_fields

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-28 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("briefing_time", sa.String(5), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"),
    )


def downgrade() -> None:
    op.drop_column("students", "timezone")
    op.drop_column("students", "briefing_time")