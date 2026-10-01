"""add portal credential lifecycle

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-10-01 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'portal_credentials',
        sa.Column('status', sa.String(length=30), nullable=False, server_default='CONNECTED'),
    )
    op.add_column(
        'portal_credentials',
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'portal_credentials',
        sa.Column('last_successful_auth_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'portal_credentials',
        sa.Column('last_auth_failure_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'portal_credentials',
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('portal_credentials', 'last_sync_at')
    op.drop_column('portal_credentials', 'last_auth_failure_at')
    op.drop_column('portal_credentials', 'last_successful_auth_at')
    op.drop_column('portal_credentials', 'connected_at')
    op.drop_column('portal_credentials', 'status')
