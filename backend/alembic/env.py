from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context
from app.agents import models as agent_models  # noqa: F401
from app.appearance import models as appearance_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.auth.tokens import models as auth_token_models  # noqa: F401
from app.invites import models as invite_models  # noqa: F401
from app.mcp.servers import models as mcp_server_models  # noqa: F401
from app.model_providers import models as model_provider_models  # noqa: F401
from app.notifications import models as notification_models  # noqa: F401
from app.observability import models as observability_models  # noqa: F401
from app.runtime.runs import models as run_models  # noqa: F401
from app.sandbox import models as sandbox_models  # noqa: F401
from app.settings import app_settings
from app.skills import models as skill_models  # noqa: F401
from app.teams import models as team_models  # noqa: F401
from app.threads import models as thread_models  # noqa: F401
from app.triggers import models as trigger_models  # noqa: F401
from app.users import models as user_models  # noqa: F401
from app.workspaces import models as workspace_models  # noqa: F401


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Keep migrations on the exact same assembled connection URL as the application.
# ConfigParser treats `%` as interpolation, so escaped credentials must double it.
database_url = app_settings.database_url.render_as_string(hide_password=False)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
