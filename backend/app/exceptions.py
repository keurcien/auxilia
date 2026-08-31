from typing import Any


def root_cause(exc: BaseException) -> BaseException:
    """Unwrap nested ExceptionGroups (TaskGroup wrappers) to the first leaf
    exception, so error reporting shows the actual failure instead of
    "unhandled errors in a TaskGroup"."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class DomainError(Exception):
    """Base for all domain exceptions."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)

    def body(self) -> dict[str, Any]:
        """The JSON body `main.py`'s handler returns for this failure.

        Overridden only where a client has to branch on the failure
        programmatically; everything else is a `detail` string, and adding a
        machine-readable field is a decision about the API contract, so it
        belongs next to the exception rather than in a handler `isinstance`
        chain.
        """
        return {"detail": self.detail}


class NotFoundError(DomainError):
    pass


class AlreadyExistsError(DomainError):
    pass


class DomainValidationError(DomainError):
    """Business-rule violation. Distinct from Pydantic's parse-time ValidationError."""


class PermissionDeniedError(DomainError):
    pass


class InvalidCredentialsError(DomainError):
    """Signin failed (wrong email/password, or password auth disabled)."""


class NoInviteError(DomainError):
    """OAuth signup attempted with no matching invite."""


class StructuredOutputError(DomainError):
    """A run with an output schema failed to produce a valid structured response."""


class StaleApprovalError(DomainError):
    """A HITL resume addressed an interrupt that is no longer pending — the
    thread moved on, usually because the approval was already handled from
    another surface (web vs Slack, a second tab). Mapped to a 409 with a
    machine-readable body so clients can tell it apart from
    `ModelUnavailableError`, the other 409 on the run-create path."""

    def body(self) -> dict[str, Any]:
        return {"error": "stale_interrupt", "detail": self.detail}


class ModelUnavailableError(DomainError):
    """The thread/trigger model can't be used right now: not in the whitelist,
    provider key missing, or disabled by a workspace admin. Mapped to a 409
    with a machine-readable body so every client (web composer, Slack,
    triggers) can branch on it without string-matching the message."""

    def __init__(self, model_id: str, reason: str):
        self.model_id = model_id
        self.reason = reason
        super().__init__(f"Model '{model_id}' is not available: {reason}")

    def body(self) -> dict[str, Any]:
        return {
            "error": "model_unavailable",
            "model_id": self.model_id,
            "detail": self.detail,
        }


#: HTTP status per domain exception — the whole translation table, in one place
#: instead of one copy-paste handler each (design review §2.3).
#:
#: A subclass with no row of its own inherits the nearest ancestor's status via
#: `status_for`'s MRO walk, so `NoInviteError` and `StructuredOutputError` are
#: 500s by inheriting `DomainError` — which is what they are, and what they get
#: today. Add a row only when a new exception wants its own code.
STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    AlreadyExistsError: 409,
    DomainValidationError: 400,
    PermissionDeniedError: 403,
    InvalidCredentialsError: 401,
    ModelUnavailableError: 409,
    StaleApprovalError: 409,
    DomainError: 500,
}


def status_for(exc: DomainError) -> int:
    """The HTTP status for `exc`, resolved through its MRO.

    `DomainError` is in `STATUS`, so the walk always terminates; the fallback
    is unreachable and exists so a caller passing something odd gets a 500
    rather than a `StopIteration`.
    """
    for cls in type(exc).__mro__:
        status = STATUS.get(cls)
        if status is not None:
            return status
    return 500  # pragma: no cover
