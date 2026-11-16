"""stamp trigger thread titles

Revision ID: w8m0o2q4s6u9
Revises: v7l9n1p3r5t8
"""

from collections.abc import Sequence

from alembic import op


revision: str = "w8m0o2q4s6u9"
down_revision: str | Sequence[str] | None = "v7l9n1p3r5t8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same format as `fire_thread_title`; threads renamed since keep their title.
    op.execute(
        """
        UPDATE threads
        SET first_message_content = triggers.name || ' / '
            || to_char(
                threads.created_at AT TIME ZONE COALESCE(triggers.timezone, 'UTC'),
                'YYYY-MM-DD HH24:MI'
            )
            || CASE WHEN triggers.timezone IS NULL THEN ' UTC' ELSE '' END
        FROM triggers
        WHERE triggers.id = threads.trigger_id
          AND threads.first_message_content = triggers.name
        """
    )


def downgrade() -> None:
    pass
