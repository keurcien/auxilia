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


class ModelUnavailableError(DomainError):
    """The thread/trigger model can't be used right now: not in the whitelist,
    provider key missing, or disabled by a workspace admin. Mapped to a 409
    with a machine-readable body so every client (web composer, Slack,
    triggers) can branch on it without string-matching the message."""

    def __init__(self, model_id: str, reason: str):
        self.model_id = model_id
        self.reason = reason
        super().__init__(f"Model '{model_id}' is not available: {reason}")
