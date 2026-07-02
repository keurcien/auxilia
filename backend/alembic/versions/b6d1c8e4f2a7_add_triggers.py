"""add triggers

Revision ID: b6d1c8e4f2a7
Revises: a1d7e9f2c3b4
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d1c8e4f2a7'
down_revision: Union[str, Sequence[str], None] = 'a1d7e9f2c3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'triggers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column('model_id', sa.String(length=255), nullable=False),
        sa.Column('cron_expression', sa.String(length=255), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_triggers_owner_id'), 'triggers', ['owner_id'], unique=False)
    op.create_index(op.f('ix_triggers_agent_id'), 'triggers', ['agent_id'], unique=False)
    # The scanner's hot query: WHERE is_active AND next_run_at <= now(),
    # every tick on every instance. Partial index keeps it tiny — paused
    # triggers (next_run_at IS NULL) never appear in it.
    op.create_index(
        'ix_triggers_due',
        'triggers',
        ['next_run_at'],
        unique=False,
        postgresql_where=sa.text('is_active AND next_run_at IS NOT NULL'),
    )

    # Link trigger-sourced threads back to their trigger for the run-history
    # view. SET NULL so deleting a trigger keeps its past threads.
    op.add_column('threads', sa.Column('trigger_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_threads_trigger_id_triggers', 'threads', 'triggers',
        ['trigger_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_threads_trigger_id'), 'threads', ['trigger_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_threads_trigger_id'), table_name='threads')
    op.drop_constraint('fk_threads_trigger_id_triggers', 'threads', type_='foreignkey')
    op.drop_column('threads', 'trigger_id')

    op.drop_index('ix_triggers_due', table_name='triggers')
    op.drop_index(op.f('ix_triggers_agent_id'), table_name='triggers')
    op.drop_index(op.f('ix_triggers_owner_id'), table_name='triggers')
    op.drop_table('triggers')
