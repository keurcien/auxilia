from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from jose import jwt

from app.auth.middleware import SlidingSessionMiddleware
from app.auth.settings import auth_settings
from app.auth.utils import (
    create_access_token,
    decode_access_token,
    renew_access_token,
)


LIFETIME = timedelta(minutes=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

app = FastAPI()
app.add_middleware(SlidingSessionMiddleware)


@app.get("/ok")
async def ok() -> dict:
    return {}


@app.get("/denied", status_code=401)
async def denied() -> dict:
    return {}


@app.post("/signout")
async def signout() -> Response:
    response = Response()
    response.delete_cookie(auth_settings.COOKIE_NAME)
    return response


def _call(method: str, path: str, token: str) -> Response:
    client = TestClient(app, cookies={auth_settings.COOKIE_NAME: token})
    return client.request(method, path)


def test_old_token_is_renewed_on_success() -> None:
    user_id = uuid4()
    res = _call("GET", "/ok", create_access_token(user_id, LIFETIME * 0.4))

    renewed = res.cookies.get(auth_settings.COOKIE_NAME)
    assert renewed is not None
    assert decode_access_token(renewed) == user_id


@pytest.mark.parametrize(
    ("method", "path", "remaining"),
    [
        ("GET", "/ok", LIFETIME * 0.9),  # still fresh
        ("GET", "/denied", LIFETIME * 0.4),  # failed request
    ],
)
def test_no_renewal(method: str, path: str, remaining: timedelta) -> None:
    res = _call(method, path, create_access_token(uuid4(), remaining))

    assert "set-cookie" not in res.headers


def test_garbage_token_is_ignored() -> None:
    assert "set-cookie" not in _call("GET", "/ok", "not-a-jwt").headers


def test_signout_is_not_overridden() -> None:
    res = _call("POST", "/signout", create_access_token(uuid4(), LIFETIME * 0.4))

    [cookie] = res.headers.get_list("set-cookie")
    assert cookie.startswith(f'{auth_settings.COOKIE_NAME}=""')


def _signed_in_ago(days: float) -> int:
    return int((datetime.now(UTC) - timedelta(days=days)).timestamp())


def test_renewal_keeps_the_sign_in_time_and_caps_at_session_max() -> None:
    signed_in = _signed_in_ago(auth_settings.SESSION_MAX_DAYS - 0.5)
    token = create_access_token(uuid4(), LIFETIME * 0.4, auth_time=signed_in)

    claims = jwt.get_unverified_claims(renew_access_token(token))

    assert claims["auth_time"] == signed_in
    # Ends at sign-in + SESSION_MAX_DAYS (12h from now), not a full lifetime.
    left = claims["exp"] - datetime.now(UTC).timestamp()
    assert abs(left - 12 * 3600) < 60


def test_no_renewal_past_session_max() -> None:
    signed_in = _signed_in_ago(auth_settings.SESSION_MAX_DAYS)
    token = create_access_token(uuid4(), LIFETIME * 0.4, auth_time=signed_in)

    assert renew_access_token(token) is None
