"""Redis-backed limits and one-time consumption for 2FA sign-in challenges."""

from uuid import UUID

from app.exceptions import InvalidCredentialsError
from app.redis_client import get_redis


_CHALLENGE_TTL_SECONDS = 10 * 60
_MAX_CHALLENGE_ATTEMPTS = 5
_MAX_USER_ATTEMPTS = 10


def _attempt_key(kind: str, value: str) -> str:
    return f"auth:2fa:{kind}:{value}"


async def record_challenge_attempt(user_id: UUID, jti: str) -> None:
    """Atomically count one guess against both the challenge and the account."""
    redis = get_redis()
    challenge_key = _attempt_key("challenge-attempts", jti)
    user_key = _attempt_key("user-attempts", str(user_id))
    used_key = _attempt_key("used", jti)

    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.exists(used_key)
        pipeline.incr(challenge_key)
        pipeline.expire(challenge_key, _CHALLENGE_TTL_SECONDS)
        pipeline.incr(user_key)
        pipeline.expire(user_key, _CHALLENGE_TTL_SECONDS)
        used, challenge_attempts, _, user_attempts, _ = await pipeline.execute()

    if (
        used
        or challenge_attempts > _MAX_CHALLENGE_ATTEMPTS
        or user_attempts > _MAX_USER_ATTEMPTS
    ):
        raise InvalidCredentialsError("Invalid or expired two-factor challenge")


async def consume_challenge(jti: str) -> None:
    """Mark a successfully verified challenge as single-use."""
    consumed = await get_redis().set(
        _attempt_key("used", jti),
        "1",
        nx=True,
        ex=_CHALLENGE_TTL_SECONDS,
    )
    if not consumed:
        raise InvalidCredentialsError("Invalid or expired two-factor challenge")
