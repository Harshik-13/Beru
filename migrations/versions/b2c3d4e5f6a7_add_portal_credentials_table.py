"""add portal credentials table

Revision ID: a1b2c3d4e5f6
Revises: 9a8b7c6d5e4f
Create Date: 2026-09-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9a8b7c6d5e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'portal_credentials',
        sa.Column('student_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('portal', sa.String(length=50), nullable=False),
        sa.Column('roll_number', sa.String(length=100), nullable=False),
        sa.Column('encrypted_password', sa.String(length=500), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_portal_credentials'),
        sa.UniqueConstraint('student_id', 'portal', name='uq_portal_credential_student_portal'),
    )


def downgrade() -> None:
    op.drop_table('portal_credentials')