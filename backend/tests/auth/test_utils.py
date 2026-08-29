"""Pure-function tests for `app/auth/utils.py`.

The auth module had no tests at all (backend design review §6.2), which is a bad
place for a coverage hole: these four functions gate every authenticated request.
"""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from jose import jwt

from app.auth.settings import auth_settings
from app.auth.utils import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


# ---------------------------------------------------------------------------
# password hashing
# ---------------------------------------------------------------------------


async def test_hash_verifies_against_its_own_password():
    hashed = await get_password_hash("correct horse battery staple")

    assert await verify_password("correct horse battery staple", hashed) is True


async def test_hash_rejects_a_wrong_password():
    hashed = await get_password_hash("correct horse battery staple")

    assert await verify_password("Correct horse battery staple", hashed) is False


async def test_hashes_are_salted_so_the_same_password_hashes_differently():
    assert await get_password_hash("same") != await get_password_hash("same")


async def test_hash_is_argon2id():
    """PAT lookup scans candidates by prefix and verifies each one, so knowing
    which algorithm is on the request path matters (§3.1 / P1-1)."""
    assert (await get_password_hash("x")).startswith("$argon2id$")


async def test_hashing_does_not_block_the_event_loop():
    """P1-2: Argon2 must run in a thread. A coroutine sharing the loop with a
    hash has to keep making progress while the hash is in flight — which it can
    only do if the hash is not running on the loop itself."""
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    beat = asyncio.create_task(heartbeat())
    try:
        await get_password_hash("some password")
    finally:
        beat.cancel()

    assert ticks > 1


# ---------------------------------------------------------------------------
# access tokens
# ---------------------------------------------------------------------------


def test_round_trips_a_user_id():
    user_id = uuid4()

    assert decode_access_token(create_access_token(user_id)) == user_id


def test_decodes_none_for_a_token_signed_with_another_key():
    user_id = uuid4()
    forged = jwt.encode(
        {"sub": str(user_id)}, "not-our-secret", algorithm=auth_settings.JWT_ALGORITHM
    )

    assert decode_access_token(forged) is None


def test_decodes_none_for_an_expired_token():
    token = create_access_token(uuid4(), expires_delta=timedelta(seconds=-1))

    assert decode_access_token(token) is None


def test_decodes_none_for_garbage():
    assert decode_access_token("not-a-jwt") is None


def test_decodes_none_when_the_subject_is_missing():
    token = jwt.encode(
        {"exp": 9999999999},
        auth_settings.JWT_SECRET_KEY,
        algorithm=auth_settings.JWT_ALGORITHM,
    )

    assert decode_access_token(token) is None


def test_decodes_none_for_a_non_uuid_subject():
    """A `sub` we can't parse must read as "not authenticated" (401), not escape
    as a ValueError the exception handlers turn into a 500."""
    token = jwt.encode(
        {"sub": "not-a-uuid", "exp": 9999999999},
        auth_settings.JWT_SECRET_KEY,
        algorithm=auth_settings.JWT_ALGORITHM,
    )

    assert decode_access_token(token) is None


def test_custom_expiry_is_honoured():
    token = create_access_token(uuid4(), expires_delta=timedelta(minutes=1))
    payload = jwt.decode(
        token,
        auth_settings.JWT_SECRET_KEY,
        algorithms=[auth_settings.JWT_ALGORITHM],
    )

    assert payload["exp"] - payload["iat"] == pytest.approx(60, abs=2)
