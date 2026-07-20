import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
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


_checkpointer_pool: AsyncConnectionPool | None = None
_checkpointer_pool_lock = asyncio.Lock()


async def _get_checkpointer_pool() -> AsyncConnectionPool:
    """Lazily open one shared psycopg pool for LangGraph checkpointing.

    `AsyncPostgresSaver.from_conn_string` dials a fresh Postgres connection per
    call, which sits on the critical path of every run; a pool amortizes that.
    Connection kwargs mirror `from_conn_string`; `check` pings a pooled
    connection before handing it out (the psycopg equivalent of
    `pool_pre_ping`).
    """
    global _checkpointer_pool
    if _checkpointer_pool is None:
        async with _checkpointer_pool_lock:
            if _checkpointer_pool is None:
                pool = AsyncConnectionPool(
                    get_psycopg_conn_string(),
                    min_size=1,
                    max_size=10,
                    open=False,
                    check=AsyncConnectionPool.check_connection,
                    kwargs={
                        "autocommit": True,
                        "prepare_threshold": 0,
                        "row_factory": dict_row,
                    },
                )
                await pool.open()
                _checkpointer_pool = pool
    return _checkpointer_pool


async def close_checkpointer_pool() -> None:
    """Release the checkpointer pool's connections (app shutdown)."""
    global _checkpointer_pool
    async with _checkpointer_pool_lock:
        if _checkpointer_pool is not None:
            await _checkpointer_pool.close()
            _checkpointer_pool = None


@asynccontextmanager
async def get_checkpointer():
    pool = await _get_checkpointer_pool()
    yield AsyncPostgresSaver(pool)
