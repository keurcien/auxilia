"""The lockfile: a pin of a source to a revision and each skill to a digest.

JSON, stable key order, newline-terminated, versioned. Digests only — small
and reviewable. Identity is the skill ``name``; ``resolved_at`` is
informational and excluded from equality.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from skillkit.errors import LockfileError
from skillkit.model import ResolvedSource


LOCK_VERSION = 1


@dataclass(frozen=True)
class LockedSkill:
    digest: str
    path: str


@dataclass(frozen=True)
class LockedSource:
    type: str
    url: str
    ref: str | None
    revision: str
    skills: dict[str, LockedSkill]
    resolved_at: str | None = None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LockedSource) and (
            self.type,
            self.url,
            self.ref,
            self.revision,
            self.skills,
        ) == (other.type, other.url, other.ref, other.revision, other.skills)

    __hash__ = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SkillStatus:
    name: str
    status: str  # added | removed | changed | unchanged
    locked_digest: str | None = None
    current_digest: str | None = None
    path_changed: bool = False


@dataclass(frozen=True)
class LockDiff:
    """Digest-level comparison. For *what* changed inside a skill, diff the
    two bundles with ``skillkit.diff.diff_bundles``."""

    revision_changed: bool
    skills: tuple[SkillStatus, ...]

    def by_status(self, status: str) -> tuple[SkillStatus, ...]:
        return tuple(s for s in self.skills if s.status == status)


@dataclass(frozen=True)
class Lockfile:
    sources: tuple[LockedSource, ...] = field(default_factory=tuple)
    version: int = LOCK_VERSION

    @classmethod
    def from_resolved(
        cls,
        resolved: ResolvedSource,
        *,
        skills: Iterable[str] | None = None,
        resolved_at: datetime | None = None,
    ) -> Lockfile:
        wanted = set(skills) if skills is not None else None
        locked = {
            s.name: LockedSkill(s.bundle.digest, s.path)
            for s in resolved.skills
            if wanted is None or s.name in wanted
        }
        if wanted is not None and (missing := wanted - set(locked)):
            raise LockfileError("not in the source: " + ", ".join(sorted(missing)))
        stamp = (resolved_at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(
            (
                LockedSource(
                    type=resolved.kind,
                    url=resolved.url,
                    ref=resolved.ref,
                    revision=resolved.revision,
                    skills=locked,
                    resolved_at=stamp,
                ),
            )
        )

    def source_for(self, url: str) -> LockedSource | None:
        for source in self.sources:
            if source.url == url:
                return source
        return None

    def diff(self, resolved: ResolvedSource) -> LockDiff:
        locked = self.source_for(resolved.url)
        if locked is None:
            raise LockfileError(f"{resolved.url} is not in the lockfile")
        current = resolved.by_name
        statuses: list[SkillStatus] = []
        for name in sorted(set(locked.skills) | set(current)):
            old = locked.skills.get(name)
            new = current.get(name)
            if old is None and new is not None:
                statuses.append(SkillStatus(name, "added", None, new.bundle.digest))
            elif new is None and old is not None:
                statuses.append(SkillStatus(name, "removed", old.digest, None))
            elif old is not None and new is not None:
                statuses.append(
                    SkillStatus(
                        name,
                        "changed" if old.digest != new.bundle.digest else "unchanged",
                        old.digest,
                        new.bundle.digest,
                        path_changed=old.path != new.path,
                    )
                )
        return LockDiff(locked.revision != resolved.revision, tuple(statuses))

    # -- serialization -----------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "sources": [
                {
                    "type": s.type,
                    "url": s.url,
                    "ref": s.ref,
                    "revision": s.revision,
                    "resolved_at": s.resolved_at,
                    "skills": {
                        name: {"digest": sk.digest, "path": sk.path}
                        for name, sk in sorted(s.skills.items())
                    },
                }
                for s in self.sources
            ],
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.dumps(), "utf-8")

    @classmethod
    def loads(cls, text: str) -> Lockfile:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LockfileError(f"not JSON: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != LOCK_VERSION:
            raise LockfileError(
                f"unsupported lockfile version {data.get('version') if isinstance(data, dict) else '?'}"
            )
        try:
            sources = tuple(
                LockedSource(
                    type=s["type"],
                    url=s["url"],
                    ref=s.get("ref"),
                    revision=s["revision"],
                    resolved_at=s.get("resolved_at"),
                    skills={
                        name: LockedSkill(sk["digest"], sk["path"])
                        for name, sk in s.get("skills", {}).items()
                    },
                )
                for s in data.get("sources", [])
            )
        except (KeyError, TypeError, AttributeError) as exc:
            # AttributeError: `"skills": null` or a list reaches `.items()`
            # before any of the key lookups do.
            raise LockfileError(f"malformed lockfile: {exc}") from exc
        return cls(sources)

    @classmethod
    def read(cls, path: str | Path) -> Lockfile:
        """A missing, unreadable or non-UTF-8 lockfile is a `LockfileError`
        like any other malformed one — callers should not have to catch
        filesystem and decoding errors separately."""
        try:
            text = Path(path).read_text("utf-8")
        except OSError as exc:
            raise LockfileError(f"cannot read lockfile {path}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise LockfileError(f"lockfile {path} is not UTF-8") from exc
        return cls.loads(text)
