"""migrate icon urls to r2 cdn

Rehost icon assets from the old GCS bucket (storage.googleapis.com/choose-assets)
to the Cloudflare R2 CDN. Editing the seed migrations only affects fresh
databases, so this data migration rewrites the prefix on existing rows.

Revision ID: f1a2b3c4d5e6
Revises: a1f4c7d2e9b3
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'a1f4c7d2e9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_PREFIX = "https://storage.googleapis.com/choose-assets/"
NEW_PREFIX = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/"

# Tables holding icon URLs seeded/entered with the old prefix.
TABLES = ("official_mcp_servers", "mcp_servers")


def _rewrite(from_prefix: str, to_prefix: str) -> None:
    for table in TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET icon_url = REPLACE(icon_url, :from_prefix, :to_prefix)
                WHERE icon_url LIKE :like_prefix
                """
            ).bindparams(
                from_prefix=from_prefix,
                to_prefix=to_prefix,
                like_prefix=from_prefix + "%",
            )
        )


def upgrade() -> None:
    _rewrite(OLD_PREFIX, NEW_PREFIX)


def downgrade() -> None:
    _rewrite(NEW_PREFIX, OLD_PREFIX)
