class DomainError(Exception):
    """Base for all domain exceptions."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class NotFoundError(DomainError):
    pass


class AlreadyExistsError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass
