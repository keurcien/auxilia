from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.settings import app_settings


engine = create_async_engine(
    app_settings.database_url,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Request-scoped session. Commits on success, rolls back on any error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


def get_psycopg_conn_string(sqlalchemy_url=None) -> str:
    """Convert a SQLAlchemy database URL to a psycopg-compatible connection string.

    Uses SQLAlchemy's URL object to ensure special characters (e.g. @ in IAM
    usernames) are properly percent-encoded, avoiding host-resolution errors.

    Args:
        sqlalchemy_url: Optional SQLAlchemy URL object or string. Defaults to
            the engine's URL if not provided.
    """
    if sqlalchemy_url is not None:
        url = make_url(sqlalchemy_url).set(drivername="postgresql")
    else:
        url = engine.url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def get_checkpointer():
    conn_string = get_psycopg_conn_string()
    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        yield checkpointer
