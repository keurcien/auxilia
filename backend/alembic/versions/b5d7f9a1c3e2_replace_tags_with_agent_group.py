"""replace tags with agent group

Revision ID: b5d7f9a1c3e2
Revises: a4c6e8f0b2d1
Create Date: 2026-10-03 05:20:00.000000

"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa

from alembic import op


revision: str = "b5d7f9a1c3e2"
down_revision: str | Sequence[str] | None = "a4c6e8f0b2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("group", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_agents_group"), "agents", ["group"], unique=False)
    op.add_column(
        "mcp_servers", sa.Column("group", sa.String(length=255), nullable=True)
    )
    op.create_index(
        op.f("ix_mcp_servers_group"), "mcp_servers", ["group"], unique=False
    )
    op.add_column("skills", sa.Column("group", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_skills_group"), "skills", ["group"], unique=False)
    op.execute(
        sa.text(
            'UPDATE agents AS agent SET "group" = tag.name '
            "FROM tags AS tag WHERE agent.tag_id = tag.id"
        )
    )

    op.drop_index(op.f("ix_agents_tag_id"), table_name="agents")
    op.drop_constraint("fk_agents_tag_id_tags", "agents", type_="foreignkey")
    op.drop_column("agents", "tag_id")
    op.drop_index(op.f("ix_tags_name"), table_name="tags")
    op.drop_table("tags")


def downgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tags_name"), "tags", ["name"], unique=True)
    op.add_column("agents", sa.Column("tag_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agents_tag_id_tags",
        "agents",
        "tags",
        ["tag_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_agents_tag_id"), "agents", ["tag_id"], unique=False)

    connection = op.get_bind()
    groups = list(
        connection.execute(
            sa.text('SELECT DISTINCT "group" FROM agents WHERE "group" IS NOT NULL')
        ).scalars()
    )
    for group in groups:
        tag_id = uuid4()
        connection.execute(
            sa.text("INSERT INTO tags (id, name) VALUES (:id, :name)"),
            {"id": tag_id, "name": group},
        )
        connection.execute(
            sa.text('UPDATE agents SET tag_id = :tag_id WHERE "group" = :name'),
            {"tag_id": tag_id, "name": group},
        )

    op.drop_index(op.f("ix_skills_group"), table_name="skills")
    op.drop_column("skills", "group")
    op.drop_index(op.f("ix_mcp_servers_group"), table_name="mcp_servers")
    op.drop_column("mcp_servers", "group")
    op.drop_index(op.f("ix_agents_group"), table_name="agents")
    op.drop_column("agents", "group")
