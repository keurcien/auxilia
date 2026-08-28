import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt
from pwdlib import PasswordHash

from app.auth.settings import auth_settings


password_hash = PasswordHash.recommended()


# Argon2id is deliberately slow and memory-hard: one verify costs tens of
# milliseconds of pure CPU. Called inline from a coroutine that blocks the event
# loop for the whole time, stalling every in-flight SSE stream on the worker, and
# the PAT prefix scan pays it once per candidate. Both entry points are therefore
# async and hand the work to a thread: argon2-cffi releases the GIL inside the
# hash, so the loop really does get that time back (design review §3.1b, P1-2).


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against the stored hash, off the event loop.
    """
    return await asyncio.to_thread(
        password_hash.verify, plain_password, hashed_password
    )


async def get_password_hash(password: str) -> str:
    """
    Hash a password with the recommended algorithm (Argon2id), off the event loop.
    """
    return await asyncio.to_thread(password_hash.hash, password)


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token for a user."""
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(UTC),
    }

    encoded_jwt = jwt.encode(
        to_encode,
        auth_settings.JWT_SECRET_KEY,
        algorithm=auth_settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> UUID | None:
    """Decode and validate a JWT access token. Returns user_id or None."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.JWT_SECRET_KEY,
            algorithms=[auth_settings.JWT_ALGORITHM],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
        return UUID(user_id_str)
    except (JWTError, ValueError):
        # ValueError: a signed token whose `sub` isn't a UUID. Treat it as
        # "not authenticated" (401) rather than letting it escape as a 500.
        return None
