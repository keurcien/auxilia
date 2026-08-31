"""One handler translates every domain failure into a response.

There used to be six near-identical handlers in `main.py` plus an
`ExceptionGroup` one that turned *any* group into a 500 — including a group
wrapping a domain exception that had already chosen its status (design review
§2.3). Now the status and the body come from `app/exceptions.py`, and the group
branch unwraps rather than swallows.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.exceptions import (
    AlreadyExistsError,
    DomainError,
    DomainValidationError,
    InvalidCredentialsError,
    ModelUnavailableError,
    NoInviteError,
    NotFoundError,
    PermissionDeniedError,
    StructuredOutputError,
    status_for,
)
from app.main import app as real_app


def _client(exc: BaseException) -> TestClient:
    """A one-route app wired to the *real* app's registered handlers.

    Copying the registration table rather than re-declaring it is the point:
    a handler deleted from `main.py` fails these tests, and the real app is
    left unmutated.
    """
    test_app = FastAPI()
    for exc_type, handler in real_app.exception_handlers.items():
        test_app.add_exception_handler(exc_type, handler)  # type: ignore[arg-type]

    @test_app.get("/boom")
    async def boom():
        raise exc

    return TestClient(test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# the mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (NotFoundError("no such agent"), 404),
        (AlreadyExistsError("already there"), 409),
        (DomainValidationError("bad shape"), 400),
        (PermissionDeniedError("nope"), 403),
        (InvalidCredentialsError("wrong password"), 401),
        (ModelUnavailableError("gpt-9", "not whitelisted"), 409),
        (DomainError("something broke"), 500),
    ],
)
def test_each_domain_exception_keeps_its_status(exc: DomainError, status: int):
    response = _client(exc).get("/boom")

    assert response.status_code == status
    assert response.json()["detail"] == exc.detail


@pytest.mark.parametrize(
    "exc", [NoInviteError("no invite"), StructuredOutputError("x")]
)
def test_a_subclass_with_no_row_inherits_its_parents_status(exc: DomainError):
    """`status_for` walks the MRO, so exceptions handled at their call site
    (`NoInviteError` becomes a 302 in the OAuth callback) need no row and still
    get `DomainError`'s 500 if one ever escapes."""
    assert status_for(exc) == 500
    assert _client(exc).get("/boom").status_code == 500


def test_model_unavailable_keeps_its_machine_readable_body():
    """The one exception whose body is more than `detail`: clients branch on
    `error` instead of string-matching the message."""
    response = _client(ModelUnavailableError("gpt-9", "disabled by an admin")).get(
        "/boom"
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": "model_unavailable",
        "model_id": "gpt-9",
        "detail": "Model 'gpt-9' is not available: disabled by an admin",
    }


# ---------------------------------------------------------------------------
# the group branch
# ---------------------------------------------------------------------------


def test_a_domain_exception_wrapped_by_a_taskgroup_keeps_its_status():
    """The regression this whole task exists for: the MCP transport and the
    toolset gather run under anyio task groups, so a domain failure raised
    beneath one arrives wrapped, and `ExceptionGroup`'s MRO never reaches
    `DomainError`. It used to become a bare 500."""
    wrapped = ExceptionGroup("unhandled errors in a TaskGroup", [NotFoundError("gone")])

    response = _client(wrapped).get("/boom")

    assert response.status_code == 404
    assert response.json() == {"detail": "gone"}


def test_it_unwraps_through_nesting():
    wrapped = ExceptionGroup(
        "outer", [ExceptionGroup("inner", [PermissionDeniedError("not yours")])]
    )

    response = _client(wrapped).get("/boom")

    assert response.status_code == 403
    assert response.json() == {"detail": "not yours"}


def test_a_group_of_something_else_is_still_a_500():
    """The handler preserves a status the code already chose; it never invents
    one. An unrelated TaskGroup crash stays an unhandled server error."""
    response = _client(ExceptionGroup("boom", [ValueError("bug")])).get("/boom")

    assert response.status_code == 500


def test_the_real_app_can_build_its_middleware_stack():
    """A guard for a trap this task walked into: Starlette asserts every
    registered handler key is a subclass of `Exception`, and it does so while
    *building the middleware stack* — which happens lazily, on the first
    request. `BaseExceptionGroup` is not an `Exception` subclass, so
    registering it imports cleanly and then 500s every route in production.
    Nothing else in the suite touches the real app's stack."""
    real_app.build_middleware_stack()
