"""drop official_mcp_servers table

The official MCP server catalog now lives in a CDN-hosted YAML file
(MCP_CATALOG_URL, snapshot bundled at app/mcp/servers/catalog.yaml) so adding a
server needs neither a migration nor a release. Nothing referenced this table —
installing a catalog entry copies its fields into a new mcp_servers row — so the
drop is safe.

The downgrade recreates the table and re-seeds it from the bundled snapshot, so
rolling back to the previous release leaves a working catalog. The shared
`mcp_auth_type` enum is deliberately left in place: mcp_servers.auth_type uses it.

Revision ID: d7b3f1c05a92
Revises: c8f4e2a91d05
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd7b3f1c05a92'
down_revision: Union[str, Sequence[str], None] = 'c8f4e2a91d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('official_mcp_servers')


def downgrade() -> None:
    from app.mcp.servers.catalog import bundled_catalog

    table = op.create_table(
        'official_mcp_servers',
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            'auth_type',
            postgresql.ENUM(
                'none', 'api_key', 'oauth2', name='mcp_auth_type', create_type=False
            ),
            nullable=False,
        ),
        sa.Column('icon_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('supports_dcr', sa.Boolean(), nullable=True),
        sa.Column(
            'id',
            sa.Uuid(),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_unique_constraint(
        'uq_official_mcp_servers_url', 'official_mcp_servers', ['url']
    )
    op.bulk_insert(
        table,
        [
            {
                'name': entry.name,
                'url': entry.url,
                'auth_type': entry.auth_type.value,
                'icon_url': entry.icon_url,
                'description': entry.description,
                'supports_dcr': entry.supports_dcr,
            }
            for entry in bundled_catalog()
        ],
    )
