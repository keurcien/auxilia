class OAuthAuthorizationRequired(Exception):
    """The user must visit ``url`` before this MCP server can be used.

    Raised at one place — the provider's authorization step — and caught at the
    MCP seam by whoever asked to connect. It is deliberately *not* translated
    into a response by a global handler any more: only endpoints whose job
    involves connecting may turn it into an auth prompt, and they do it through
    normal control flow (design review §2.4).
    """

    def __init__(self, url: str):
        self.url = url
        super().__init__(url)


def as_oauth_required(exc: BaseException) -> OAuthAuthorizationRequired | None:
    """Find an `OAuthAuthorizationRequired` inside `exc`, however it is wrapped.

    The implicit 401 fires deep inside the SDK's httpx auth flow. By the time a
    caller sees it, it may be plain, inside an ``ExceptionGroup`` (anyio task
    groups), or the explicit *cause* of a wrapper — FastMCP reports a session
    that never came up as ``RuntimeError("Client failed to connect: …")``
    raised ``from`` the real failure. This function is the one place that knows
    that — it is what lets every caller write a plain
    ``except OAuthAuthorizationRequired``.

    Only ``__cause__`` (an explicit ``raise … from``) is followed, never
    ``__context__``: an exception raised while *handling* the requirement is a
    different failure, not the requirement itself.

    Returns ``None`` when nothing in the tree needs authorization.
    """
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OAuthAuthorizationRequired):
            return current
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
    return None
