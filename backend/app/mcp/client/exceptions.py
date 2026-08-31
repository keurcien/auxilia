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

    The implicit 401 fires deep inside the SDK's httpx auth flow, which runs
    under anyio task groups, so a caller can receive it plainly, inside an
    ExceptionGroup, or inside a group inside a group. This function is the one
    place that knows that — it is what lets every caller write a plain
    ``except OAuthAuthorizationRequired``, and what let the app-global
    ExceptionGroup handler go away.

    Returns ``None`` when nothing in the tree needs authorization.
    """
    if isinstance(exc, OAuthAuthorizationRequired):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        matches = exc.subgroup(OAuthAuthorizationRequired)
        if matches is not None:
            return _first_leaf(matches)
    return None


def _first_leaf(group: BaseExceptionGroup) -> OAuthAuthorizationRequired:
    """The first `OAuthAuthorizationRequired` in an already-filtered subgroup.

    A subgroup keeps the original nesting, so the match can sit several levels
    down; every leaf in it matches by construction.
    """
    exc: BaseException = group
    while isinstance(exc, BaseExceptionGroup):
        exc = exc.exceptions[0]
    if not isinstance(exc, OAuthAuthorizationRequired):  # pragma: no cover
        raise TypeError(f"subgroup yielded a non-matching leaf: {exc!r}")
    return exc
