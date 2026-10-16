from fastapi import Response
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.settings import auth_settings
from app.auth.utils import attach_auth_cookie, renew_access_token


class SlidingSessionMiddleware:
    """Re-issue the session cookie on any successful request once the token is
    past half its lifetime (see `renew_access_token`).

    Pure ASGI rather than a dependency: FastAPI drops dependency-set cookies when
    a route returns its own `Response` (the streaming and run endpoints do).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = (
            HTTPConnection(scope).cookies.get(auth_settings.COOKIE_NAME)
            if scope["type"] == "http"
            else None
        )
        renewed = renew_access_token(token) if token else None
        if renewed is None:
            await self.app(scope, receive, send)
            return

        carrier = Response()
        attach_auth_cookie(carrier, renewed)
        cookie = carrier.headers["set-cookie"]

        async def send_renewed(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                headers = MutableHeaders(scope=message)
                # Sign-in / sign-out set or delete the cookie themselves — theirs wins.
                own = f"{auth_settings.COOKIE_NAME}="
                if not any(v.startswith(own) for v in headers.getlist("set-cookie")):
                    headers.append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_renewed)
