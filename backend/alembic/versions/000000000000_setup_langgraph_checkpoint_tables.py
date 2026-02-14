"""setup_langgraph_checkpoint_tables

Revision ID: 000000000000
Revises:
Create Date: 2025-12-02 00:00:00.000000

This migration sets up the LangGraph checkpoint tables required by
langgraph-checkpoint-postgres. It must run before all other migrations.

See: https://pypi.org/project/langgraph-checkpoint-postgres/
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "000000000000"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set up LangGraph checkpoint tables using the library's setup method."""
    from langgraph.checkpoint.postgres import PostgresSaver

    # Get the database URL from Alembic's connection binding.
    # Using SQLAlchemy's URL object ensures special characters (e.g. @ in
    # usernames for IAM auth) are properly percent-encoded, which avoids
    # host-resolution errors from psycopg's connection string parser.
    bind = op.get_bind()
    url = bind.engine.url.set(drivername="postgresql")
    db_url = url.render_as_string(hide_password=False)

    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        checkpointer.setup()


def downgrade() -> None:
    """Drop LangGraph checkpoint tables.

    Note: The checkpoint tables store conversation state. Dropping them
    will permanently delete all checkpoint data.
    """
    # Drop tables created by langgraph-checkpoint-postgres
    # These are the tables created by the setup() method
    op.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations CASCADE")
