"""agent sandbox bindings: link table, env-config conversion, drop flag

Converts the env-driven sandbox singleton into registry data:
1. creates agent_sandboxes (agent <-> sandboxes link, one per agent),
2. one-shot conversion of the SANDBOX_PROVIDER env config into a normal,
   editable sandboxes row (skipped if an identical provider+url row exists —
   e.g. one already created through the UI),
3. binds every agent with has_code_interpreter=true to that row,
4. drops agents.has_code_interpreter.

After this migration the DB is the sole source of sandbox configuration;
the SANDBOX_* / OPEN_SANDBOX_* / CLOUD_RUN_SANDBOX_* env vars are dead.

Revision ID: 7c5a92e14b03
Revises: 3e9d41c7a802
Create Date: 2026-08-22 11:00:00.000000

"""

import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7c5a92e14b03"
down_revision: str | Sequence[str] | None = "3e9d41c7a802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _env_sandbox() -> tuple[str, str, str | None, dict, str] | None:
    """(provider, url, secret, config_extras, name) from env, or None."""
    from app.sandbox.settings import SandboxSettings

    settings = SandboxSettings()
    if not settings.enabled:
        return None
    if settings.provider == "cloudrun":
        cr = settings.cloudrun
        # `enabled` only checks for None — an empty-string URL or secret would
        # produce a row that runtime validation rejects.
        if not cr.gateway_url or not cr.gateway_secret:
            return None
        return (
            "cloudrun",
            cr.gateway_url,
            cr.gateway_secret,
            {
                "default_packages": list(cr.default_packages),
                "timeout": cr.timeout,
                "gcs_bucket": cr.gcs_bucket,
                "snapshot_prefix": cr.snapshot_prefix,
                "allow_egress": cr.allow_egress,
            },
            "Cloud Run",
        )
    osb = settings.opensandbox
    if not osb.domain:
        return None
    return (
        "opensandbox",
        osb.domain,
        osb.api_key,
        {
            "default_packages": list(osb.default_packages),
            "timeout": osb.timeout,
            "default_image": osb.default_image,
            "volume_mounts": osb.parsed_volume_mounts,
            "use_server_proxy": osb.use_server_proxy,
        },
        "OpenSandbox",
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_sandboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("sandbox_id", sa.Uuid(), nullable=False),
        sa.Column("tools", JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sandbox_id"], ["sandboxes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_sandbox"),
    )
    # The delete guard and bulk detach filter on sandbox_id.
    op.create_index("ix_agent_sandboxes_sandbox_id", "agent_sandboxes", ["sandbox_id"])

    bind = op.get_bind()
    env = _env_sandbox()
    if env is not None:
        provider, url, secret, config, name = env
        existing = bind.execute(
            sa.text("SELECT id FROM sandboxes WHERE provider = :p AND url = :u"),
            {"p": provider, "u": url},
        ).first()
        if existing:
            sandbox_id = existing[0]
        else:
            from app.utils.encryption import encrypt_value

            sandbox_id = uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO sandboxes "
                    "(id, name, provider, url, config, encrypted_secret) "
                    "VALUES (:id, :name, CAST(:p AS sandboxprovidertype), :url, "
                    "CAST(:config AS jsonb), :secret)"
                ),
                {
                    "id": sandbox_id,
                    "name": name,
                    "p": provider,
                    "url": url,
                    "config": json.dumps(config),
                    "secret": encrypt_value(secret) if secret else None,
                },
            )
        bind.execute(
            sa.text(
                "INSERT INTO agent_sandboxes (id, agent_id, sandbox_id) "
                "SELECT gen_random_uuid(), id, :sid FROM agents "
                "WHERE has_code_interpreter = true"
            ),
            {"sid": sandbox_id},
        )
    else:
        # Never drop the flag silently: agents still carrying it would lose
        # their sandbox with no trace. Run this upgrade in an environment
        # where the SANDBOX_* env vars are set (so the conversion runs), or
        # clear the flags first if that configuration is truly gone.
        flagged = bind.execute(
            sa.text("SELECT count(*) FROM agents WHERE has_code_interpreter = true")
        ).scalar()
        if flagged:
            raise RuntimeError(
                f"{flagged} agent(s) still have has_code_interpreter=true but no "
                "sandbox env configuration is present to convert them. Set the "
                "SANDBOX_* env vars for this upgrade, or clear the flags first."
            )

    op.drop_column("agents", "has_code_interpreter")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "has_code_interpreter",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE agents SET has_code_interpreter = true "
        "WHERE id IN (SELECT agent_id FROM agent_sandboxes)"
    )
    op.drop_index("ix_agent_sandboxes_sandbox_id", table_name="agent_sandboxes")
    op.drop_table("agent_sandboxes")
