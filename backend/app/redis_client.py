"""The app-wide async Redis client.

A single shared connection pool, built from `app_settings`, used by the durable
run runtime (and anything else that needs Redis outside an HTTP request, where
`request.app.state` isn't available). Created lazily so importing this module
doesn't open a connection at import time; closed once in the FastAPI lifespan.
"""

from redis.asyncio import Redis

from app.settings import app_settings


_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the shared async Redis client, creating it on first use."""
    global _redis
    if _redis is None:
        _redis = Redis(
            host=app_settings.redis_host,
            port=app_settings.redis_port,
            db=app_settings.redis_db,
            password=app_settings.redis_password,
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the shared client. Called once on app shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
