"""add attendance tables

Revision ID: 9a8b7c6d5e4f
Revises: 8f7e3a2b1c9d
Create Date: 2026-09-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '9a8b7c6d5e4f'
down_revision: Union[str, None] = '8f7e3a2b1c9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types first
    attendance_source_enum = sa.Enum(
        'doctus',
        name='attendance_source', native_enum=False
    )

    attendance_source_enum.create(op.get_bind(), checkfirst=True)

    # attendance_snapshots table
    op.create_table(
        'attendance_snapshots',
        sa.Column('student_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source', sa.Enum('doctus', name='attendance_source', native_enum=False), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('semester_id', sa.String(length=50), nullable=True),
        sa.Column('overall_attended', sa.Integer(), nullable=False),
        sa.Column('overall_conducted', sa.Integer(), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['student_id'],
            ['students.id'],
            name='fk_attendance_snapshots_student_id_students',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_attendance_snapshots'),
        sa.CheckConstraint('overall_attended >= 0', name='ck_attendance_attended_nonneg'),
        sa.CheckConstraint('overall_conducted >= 0', name='ck_attendance_conducted_nonneg'),
        sa.CheckConstraint('overall_attended <= overall_conducted', name='ck_attendance_attended_le_conducted'),
    )

    op.create_index(
        'ix_attendance_snapshots_student_id',
        'attendance_snapshots',
        ['student_id'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_snapshots_student_id_captured_at',
        'attendance_snapshots',
        ['student_id', 'captured_at'],
        unique=False,
    )

    # subject_attendance table
    op.create_table(
        'subject_attendance',
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_code', sa.String(length=20), nullable=False),
        sa.Column('subject_name', sa.String(length=100), nullable=True),
        sa.Column('monthly_period', sa.String(length=20), nullable=True),
        sa.Column('monthly_attended', sa.Integer(), nullable=True),
        sa.Column('monthly_conducted', sa.Integer(), nullable=True),
        sa.Column('cumulative_attended', sa.Integer(), nullable=False),
        sa.Column('cumulative_conducted', sa.Integer(), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['snapshot_id'],
            ['attendance_snapshots.id'],
            name='fk_subject_attendance_snapshot_id_attendance_snapshots',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_subject_attendance'),
        sa.CheckConstraint('cumulative_attended >= 0', name='ck_subj_cum_attended_nonneg'),
        sa.CheckConstraint('cumulative_conducted >= 0', name='ck_subj_cum_conducted_nonneg'),
        sa.CheckConstraint('cumulative_attended <= cumulative_conducted', name='ck_subj_cum_attended_le_conducted'),
        sa.CheckConstraint('monthly_attended IS NULL OR monthly_attended >= 0', name='ck_subj_monthly_attended_nonneg'),
        sa.CheckConstraint('monthly_conducted IS NULL OR monthly_conducted >= 0', name='ck_subj_monthly_conducted_nonneg'),
        sa.CheckConstraint('monthly_attended IS NULL OR monthly_conducted IS NULL OR monthly_attended <= monthly_conducted', name='ck_subj_monthly_attended_le_conducted'),
    )

    op.create_index(
        'ix_subject_attendance_snapshot_id',
        'subject_attendance',
        ['snapshot_id'],
        unique=False,
    )
    op.create_index(
        'ix_subject_attendance_snapshot_id_subject_code',
        'subject_attendance',
        ['snapshot_id', 'subject_code'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_subject_attendance_snapshot_id_subject_code', table_name='subject_attendance')
    op.drop_index('ix_subject_attendance_snapshot_id', table_name='subject_attendance')
    op.drop_table('subject_attendance')

    op.drop_index('ix_attendance_snapshots_student_id_captured_at', table_name='attendance_snapshots')
    op.drop_index('ix_attendance_snapshots_student_id', table_name='attendance_snapshots')
    op.drop_table('attendance_snapshots')

    sa.Enum(name='attendance_source', native_enum=False).drop(op.get_bind(), checkfirst=True)