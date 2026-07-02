"""add tags

Revision ID: a1d7e9f2c3b4
Revises: f3c2b1a09d8e
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d7e9f2c3b4'
down_revision: Union[str, Sequence[str], None] = 'f3c2b1a09d8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tags',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tags_name'), 'tags', ['name'], unique=True)

    op.add_column('agents', sa.Column('tag_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_agents_tag_id_tags', 'agents', 'tags', ['tag_id'], ['id'],
        ondelete='SET NULL',
    )
    # The agents list groups by tag; index the FK for that lookup and the
    # tag-delete SET NULL sweep.
    op.create_index(op.f('ix_agents_tag_id'), 'agents', ['tag_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_agents_tag_id'), table_name='agents')
    op.drop_constraint('fk_agents_tag_id_tags', 'agents', type_='foreignkey')
    op.drop_column('agents', 'tag_id')

    op.drop_index(op.f('ix_tags_name'), table_name='tags')
    op.drop_table('tags')
