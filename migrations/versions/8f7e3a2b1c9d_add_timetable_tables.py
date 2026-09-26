"""add timetable tables

Revision ID: 8f7e3a2b1c9d
Revises: 14fe74f16b74
Create Date: 2026-09-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '8f7e3a2b1c9d'
down_revision: Union[str, None] = '14fe74f16b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types first
    timetable_status_enum = sa.Enum(
        'uploaded', 'extracting', 'review_required', 'confirmed', 'archived', 'failed',
        name='timetable_status', native_enum=False
    )
    activity_type_enum = sa.Enum(
        'academic', 'lab', 'break', 'activity',
        name='activity_type', native_enum=False
    )
    lab_batch_enum = sa.Enum(
        'unknown', 'batch_1', 'batch_2',
        name='lab_batch', native_enum=False
    )

    timetable_status_enum.create(op.get_bind(), checkfirst=True)
    activity_type_enum.create(op.get_bind(), checkfirst=True)
    lab_batch_enum.create(op.get_bind(), checkfirst=True)

    # Add lab_batch column to students table
    lab_batch_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'students',
        sa.Column(
            'lab_batch',
            lab_batch_enum,
            nullable=False,
            server_default='unknown'
        )
    )

    # timetables table
    op.create_table(
        'timetables',
        sa.Column('student_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('academic_year', sa.String(length=20), nullable=True),
        sa.Column('regulation', sa.String(length=50), nullable=True),
        sa.Column('programme', sa.String(length=100), nullable=True),
        sa.Column('branch', sa.String(length=100), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('semester', sa.Integer(), nullable=True),
        sa.Column('section', sa.String(length=10), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('default_classroom', sa.String(length=100), nullable=True),
        sa.Column('status', timetable_status_enum, nullable=False, server_default='uploaded'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['student_id'],
            ['students.id'],
            name='fk_timetables_student_id_students',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_timetables'),
    )

    op.create_index(
        'ix_timetables_student_id',
        'timetables',
        ['student_id'],
        unique=False,
    )
    op.create_index(
        'ix_timetables_student_id_status',
        'timetables',
        ['student_id', 'status'],
        unique=False,
    )

    # timetable_entries table
    op.create_table(
        'timetable_entries',
        sa.Column('timetable_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('activity_name', sa.String(length=200), nullable=False),
        sa.Column('activity_type', activity_type_enum, nullable=False),
        sa.Column('course_code', sa.String(length=20), nullable=True),
        sa.Column('room', sa.String(length=50), nullable=True),
        sa.Column('faculty', sa.String(length=100), nullable=True),
        sa.Column('lab_batch', lab_batch_enum, nullable=True),
        sa.Column('extraction_confidence', sa.Float(), nullable=True),
        sa.Column('extraction_notes', sa.Text(), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['timetable_id'],
            ['timetables.id'],
            name='fk_timetable_entries_timetable_id_timetables',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_timetable_entries'),
    )

    op.create_index(
        'ix_timetable_entries_timetable_id',
        'timetable_entries',
        ['timetable_id'],
        unique=False,
    )
    op.create_index(
        'ix_timetable_entries_timetable_id_day',
        'timetable_entries',
        ['timetable_id', 'day_of_week'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_timetable_entries_timetable_id_day', table_name='timetable_entries')
    op.drop_index('ix_timetable_entries_timetable_id', table_name='timetable_entries')
    op.drop_table('timetable_entries')

    op.drop_index('ix_timetables_student_id_status', table_name='timetables')
    op.drop_index('ix_timetables_student_id', table_name='timetables')
    op.drop_table('timetables')

    op.drop_column('students', 'lab_batch')

    # Drop enums
    sa.Enum(name='lab_batch', native_enum=False).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='activity_type', native_enum=False).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='timetable_status', native_enum=False).drop(op.get_bind(), checkfirst=True)