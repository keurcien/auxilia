"""One base exception, specific subclasses, no bare raises.

The ``SourceError`` leaves are distinct *types* on purpose: a consumer must
tell "not configured" (auth), "permanently broken" (revision gone), "nothing
there yet" (empty) and "temporarily broken" (host unreachable) apart without
matching strings.
"""


class SkillkitError(Exception):
    """Base for everything this package raises."""


class SourceError(SkillkitError):
    """Resolution failed. See the subclasses for *why*."""


class AuthenticationError(SourceError):
    """The host refused the credentials (401/403), or wanted some."""


class RevisionNotFound(SourceError):
    """The repository, ref or path does not exist at the host."""


class EmptyRepository(SourceError):
    """The repository exists and the credentials work, but it holds no
    commits — so there is no ref to resolve and nothing to read. GitHub says
    409 for this; without its own type it landed in the catch-all and was
    reported as if the host were unreachable."""


class SourceUnavailable(SourceError):
    """The host could not be reached or answered with a server error."""


class ValidationError(SkillkitError):
    """Content that cannot be turned into a skill set at all (an unsafe
    archive, a symlink). Per-skill problems are `Issue`s, not exceptions."""

    def __init__(self, message: str, code: str = "E000") -> None:
        super().__init__(message)
        self.code = code


class LockfileError(SkillkitError):
    """A lockfile that cannot be read or has an unsupported version."""


class LimitExceeded(SkillkitError):
    """A download or an archive is over the caller's limits."""
