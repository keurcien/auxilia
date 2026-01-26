"""create_mcp_server_oauth_credentials_table

Revision ID: a1b2c3d4e5f6
Revises: 60eb74a86009
Create Date: 2026-01-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e75ab54f0585'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mcp_server_oauth_credentials',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('mcp_server_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('client_secret_encrypted', sa.Text(), nullable=False),
    sa.Column('token_endpoint_auth_method', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mcp_server_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('mcp_server_oauth_credentials')
