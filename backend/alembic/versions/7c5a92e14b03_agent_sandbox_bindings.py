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

import base64
import hashlib
import json
import os
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7c5a92e14b03"
down_revision: str | Sequence[str] | None = "3e9d41c7a802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# This migration reads the environment and the database, and imports nothing
# from `app`. It used to build `app.sandbox.settings.SandboxSettings` and call
# `app.utils.encryption.encrypt_value`; the settings module was later deleted
# by the multi-sandbox work, and from then on `alembic upgrade head` on an
# empty database died here — several revisions before anything it was meant to
# migrate. A migration is a historical record: the schema it describes stops
# changing, while the application around it does not, so it cannot borrow the
# application's code and stay correct. The env names, defaults and Fernet
# format below are frozen copies of what those modules held at this revision.
_DEFAULT_TIMEOUT = 30 * 60


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    return raw.lower() in ("1", "true", "yes", "on") if raw else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    """A JSON array (what pydantic-settings accepted) or a comma-separated one."""
    raw = _env(name)
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return [str(item) for item in json.loads(raw)]
        except ValueError:
            return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _encrypt(value: str) -> str:
    """`app.utils.encryption.encrypt_value`, frozen: Fernet under a key derived
    from the deployment-wide salt. Reproduced rather than imported so this
    migration cannot break when that module moves."""
    salt = _env("SALT") or _env("MCP_API_KEY_ENCRYPTION_SALT")
    if not salt:
        raise RuntimeError(
            "A sandbox secret has to be encrypted to convert the environment "
            "configuration into a sandboxes row, but SALT is not set."
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(salt.encode()).digest())
    return Fernet(key).encrypt(value.encode()).decode()


def _env_sandbox() -> tuple[str, str, str | None, dict, str] | None:
    """(provider, url, secret, config_extras, name) from env, or None."""
    provider = _env("SANDBOX_PROVIDER") or "opensandbox"
    if provider == "cloudrun":
        # Both are required: an empty-string URL or secret would produce a row
        # that runtime validation rejects.
        url, secret = _env("CLOUD_RUN_SANDBOX_GATEWAY_URL"), _env(
            "CLOUD_RUN_SANDBOX_GATEWAY_SECRET"
        )
        if not url or not secret:
            return None
        return (
            "cloudrun",
            url,
            secret,
            {
                "default_packages": _env_list("CLOUD_RUN_SANDBOX_DEFAULT_PACKAGES"),
                "timeout": _env_int("CLOUD_RUN_SANDBOX_TIMEOUT", _DEFAULT_TIMEOUT),
                "gcs_bucket": _env("CLOUD_RUN_SANDBOX_GCS_BUCKET") or None,
                "snapshot_prefix": _env("CLOUD_RUN_SANDBOX_SNAPSHOT_PREFIX")
                or "sandbox-snapshots/",
                "allow_egress": _env_bool("CLOUD_RUN_SANDBOX_ALLOW_EGRESS", False),
            },
            "Cloud Run",
        )
    domain = _env("OPEN_SANDBOX_DOMAIN")
    if not domain:
        return None
    return (
        "opensandbox",
        domain,
        _env("OPEN_SANDBOX_API_KEY") or None,
        {
            "default_packages": _env_list("OPEN_SANDBOX_DEFAULT_PACKAGES"),
            "timeout": _env_int("OPEN_SANDBOX_TIMEOUT", _DEFAULT_TIMEOUT),
            "default_image": _env("OPEN_SANDBOX_DEFAULT_IMAGE") or "python:3.12-slim",
            "volume_mounts": _env_list("OPEN_SANDBOX_VOLUME_MOUNTS"),
            "use_server_proxy": _env_bool("OPEN_SANDBOX_USE_SERVER_PROXY", True),
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
                    "secret": _encrypt(secret) if secret else None,
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
