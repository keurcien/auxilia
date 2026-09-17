"""skillkit — resolve, discover, validate, digest, pin, diff and check Agent
Skills from a git host, an archive or a directory. See docs/skillkit-spec.md."""

from skillkit.diff import FileChange, SkillDiff, diff_bundles
from skillkit.digest import bundle_digest, set_digest
from skillkit.errors import (
    AuthenticationError,
    LimitExceeded,
    LockfileError,
    RevisionNotFound,
    SkillkitError,
    SourceError,
    SourceUnavailable,
    ValidationError,
)
from skillkit.lock import LockDiff, Lockfile
from skillkit.model import (
    Bundle,
    Frontmatter,
    Issue,
    Limits,
    Report,
    ResolvedSource,
    Skill,
)
from skillkit.requirements import (
    EnvironmentManifest,
    Requirements,
    Verdict,
    check,
    parse_requirements,
)
from skillkit.sources import (
    ArchiveSource,
    CredentialsProvider,
    GitHubSource,
    GitLabSource,
    HostedSource,
    LocalSource,
    SkillSource,
    StaticCredentials,
    resolve_tree,
)
from skillkit.validate import validate_bundle


__all__ = [
    "ArchiveSource",
    "AuthenticationError",
    "Bundle",
    "CredentialsProvider",
    "EnvironmentManifest",
    "FileChange",
    "Frontmatter",
    "GitHubSource",
    "GitLabSource",
    "HostedSource",
    "Issue",
    "LimitExceeded",
    "Limits",
    "LocalSource",
    "LockDiff",
    "Lockfile",
    "LockfileError",
    "Report",
    "Requirements",
    "ResolvedSource",
    "RevisionNotFound",
    "Skill",
    "SkillDiff",
    "SkillSource",
    "SkillkitError",
    "SourceError",
    "SourceUnavailable",
    "StaticCredentials",
    "ValidationError",
    "Verdict",
    "bundle_digest",
    "check",
    "diff_bundles",
    "parse_requirements",
    "resolve_tree",
    "set_digest",
    "validate_bundle",
]
