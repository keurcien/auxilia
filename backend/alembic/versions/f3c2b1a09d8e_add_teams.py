"""add teams

Revision ID: f3c2b1a09d8e
Revises: e4f5a6b7c8d9
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c2b1a09d8e'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'teams',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_teams_name'), 'teams', ['name'], unique=True)

    op.create_table(
        'agent_teams',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column('team_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'team_id', name='uq_agent_team'),
    )
    # The unique constraint leads with agent_id; team-grant lookups and the
    # team-delete cascade filter by team_id, so index that column too.
    op.create_index(op.f('ix_agent_teams_team_id'), 'agent_teams', ['team_id'], unique=False)

    op.add_column('users', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_users_team_id_teams', 'users', 'teams', ['team_id'], ['id'],
        ondelete='SET NULL',
    )

    op.add_column('invites', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_invites_team_id_teams', 'invites', 'teams', ['team_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_invites_team_id_teams', 'invites', type_='foreignkey')
    op.drop_column('invites', 'team_id')

    op.drop_constraint('fk_users_team_id_teams', 'users', type_='foreignkey')
    op.drop_column('users', 'team_id')

    op.drop_table('agent_teams')
    op.drop_index(op.f('ix_teams_name'), table_name='teams')
    op.drop_table('teams')
