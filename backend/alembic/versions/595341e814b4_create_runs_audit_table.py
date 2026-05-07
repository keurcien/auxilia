"""create runs audit table

Revision ID: 595341e814b4
Revises: a57400e4fb11
Create Date: 2026-05-07 17:52:12.222208

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '595341e814b4'
down_revision: Union[str, Sequence[str], None] = 'a57400e4fb11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'runs',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'PENDING', 'RUNNING', 'INTERRUPTED', 'SUCCESS',
                'ERROR', 'CANCELLED', 'TIMEOUT', name='runstate',
            ),
            nullable=False,
        ),
        sa.Column(
            'multitask_strategy',
            sa.Enum('REJECT', 'ENQUEUE', 'INTERRUPT', 'ROLLBACK', name='multitaskstrategy'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'cancellation_reason',
            sa.Enum('USER', 'REPLACED', 'TIMEOUT', 'SYSTEM', name='cancellationreason'),
            nullable=True,
        ),
        sa.Column('error', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('interrupt', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('input_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('model_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('token_usage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_runs_status'), 'runs', ['status'], unique=False)
    op.create_index(op.f('ix_runs_thread_id'), 'runs', ['thread_id'], unique=False)
    op.create_index(op.f('ix_runs_user_id'), 'runs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_runs_user_id'), table_name='runs')
    op.drop_index(op.f('ix_runs_thread_id'), table_name='runs')
    op.drop_index(op.f('ix_runs_status'), table_name='runs')
    op.drop_table('runs')
    op.execute("DROP TYPE IF EXISTS runstate")
    op.execute("DROP TYPE IF EXISTS multitaskstrategy")
    op.execute("DROP TYPE IF EXISTS cancellationreason")
