import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Response
from jose import JWTError, jwt
from pwdlib import PasswordHash

from app.auth.settings import auth_settings
from app.auth.token_types import TokenKind


password_hash = PasswordHash.recommended()
REMEMBER_ME_REFRESH_DAYS = 180


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: UUID
    auth_time: int
    remember_me: bool = False
    actor_id: UUID | None = None
    actor_workspace_id: UUID | None = None

    @property
    def is_supervised(self) -> bool:
        return self.actor_id is not None


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


def create_access_token(
    user_id: UUID,
    expires_delta: timedelta | None = None,
    auth_time: int | None = None,
    *,
    remember_me: bool = False,
    actor_id: UUID | None = None,
    actor_workspace_id: UUID | None = None,
) -> str:
    """Create a typed session token, retaining the original sign-in time."""
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    elif remember_me:
        session_started_at = (
            datetime.fromtimestamp(auth_time, UTC) if auth_time is not None else now
        )
        expire = session_started_at + timedelta(days=auth_settings.REMEMBER_ME_DAYS)
    else:
        expire = now + timedelta(minutes=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": str(user_id),
        "token_type": TokenKind.session,
        "exp": expire,
        "iat": now,
        "auth_time": auth_time if auth_time is not None else int(now.timestamp()),
    }
    if remember_me:
        to_encode["remember_me"] = True
    if actor_id is not None:
        to_encode["act"] = {"sub": str(actor_id)}
        if actor_workspace_id is not None:
            to_encode["act_workspace"] = str(actor_workspace_id)

    encoded_jwt = jwt.encode(
        to_encode,
        auth_settings.JWT_SECRET_KEY,
        algorithm=auth_settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_session_token(token: str) -> SessionClaims | None:
    """Decode and validate a browser/API session token."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.JWT_SECRET_KEY,
            algorithms=[auth_settings.JWT_ALGORITHM],
        )
        token_type = payload.get("token_type")
        # Keep pre-token-type access tokens valid during upgrades, but never
        # accept a scoped challenge as an authenticated session.
        if token_type != TokenKind.session and (
            token_type is not None or payload.get("scope") is not None
        ):
            return None
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
        actor = payload.get("act")
        if actor is not None and (
            not isinstance(actor, dict) or not isinstance(actor.get("sub"), str)
        ):
            return None
        actor_id = UUID(actor["sub"]) if actor is not None else None
        actor_workspace = payload.get("act_workspace")
        if actor_workspace is not None and (
            actor_id is None or not isinstance(actor_workspace, str)
        ):
            return None
        actor_workspace_id = (
            UUID(actor_workspace) if isinstance(actor_workspace, str) else None
        )
        return SessionClaims(
            user_id=UUID(user_id_str),
            auth_time=int(payload.get("auth_time", payload["iat"])),
            remember_me=payload.get("remember_me") is True,
            actor_id=actor_id,
            actor_workspace_id=actor_workspace_id,
        )
    except JWTError, KeyError, TypeError, ValueError:
        # ValueError: a signed token whose `sub` isn't a UUID. Treat it as
        # "not authenticated" (401) rather than letting it escape as a 500.
        return None


def decode_access_token(token: str) -> UUID | None:
    """Decode and validate a JWT access token. Returns user_id or None."""
    claims = decode_session_token(token)
    return claims.user_id if claims is not None else None


def renew_access_token(token: str) -> str | None:
    """Refresh active sessions without extending their absolute session cap."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.JWT_SECRET_KEY,
            algorithms=[auth_settings.JWT_ALGORITHM],
        )
        token_type = payload.get("token_type")
        # Preserve upgrade compatibility without ever promoting a scoped 2FA
        # challenge into a full session.
        if token_type != TokenKind.session and (
            token_type is not None or payload.get("scope") is not None
        ):
            return None
        claims = decode_session_token(token)
        if claims is None:
            return None
        now = datetime.now(UTC)
        remaining = datetime.fromtimestamp(payload["exp"], UTC) - now
        if claims.remember_me:
            issued_at = datetime.fromtimestamp(payload["iat"], UTC)
            session_left = (
                datetime.fromtimestamp(claims.auth_time, UTC)
                + timedelta(days=auth_settings.REMEMBER_ME_DAYS)
                - now
            )
            if (
                now - issued_at < timedelta(days=REMEMBER_ME_REFRESH_DAYS)
                or session_left <= timedelta()
            ):
                return None
            return create_access_token(
                claims.user_id,
                expires_delta=session_left,
                auth_time=claims.auth_time,
                remember_me=True,
                actor_id=claims.actor_id,
                actor_workspace_id=claims.actor_workspace_id,
            )
        session_left = (
            datetime.fromtimestamp(claims.auth_time, UTC)
            + timedelta(days=auth_settings.SESSION_MAX_DAYS)
            - now
        )
    except JWTError, KeyError, TypeError, ValueError:
        return None

    lifetime = timedelta(minutes=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    if remaining >= lifetime / 2 or session_left <= remaining:
        return None
    return create_access_token(
        claims.user_id,
        expires_delta=min(lifetime, session_left),
        auth_time=claims.auth_time,
        remember_me=claims.remember_me,
        actor_id=claims.actor_id,
        actor_workspace_id=claims.actor_workspace_id,
    )


def attach_auth_cookie(response: Response, token: str) -> None:
    claims = decode_session_token(token)
    remember_me = claims is not None and claims.remember_me
    response.set_cookie(
        key=auth_settings.COOKIE_NAME,
        value=token,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=(
            auth_settings.REMEMBER_ME_DAYS * 24 * 60 * 60
            if remember_me
            else auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        ),
    )
