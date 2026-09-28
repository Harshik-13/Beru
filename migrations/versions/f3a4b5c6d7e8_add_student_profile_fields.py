"""add_student_profile_fields

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-28 16:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("name", sa.String(100), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("attendance_target", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("students", "attendance_target")
    op.drop_column("students", "name")
