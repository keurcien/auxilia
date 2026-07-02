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
