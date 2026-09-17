"""The source protocol, and the one function every source ends in.

``resolve()`` is the only phase that touches a network or a disk. It yields a
tree (POSIX path → bytes); ``resolve_tree`` turns the tree into a
``ResolvedSource`` — discovery, frontmatter, validation — as a pure function.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from skillkit import frontmatter as fm
from skillkit.discovery import discover
from skillkit.model import Bundle, Issue, Limits, ResolvedSource, Skill
from skillkit.validate import duplicate_name_issues, validate_bundle


@runtime_checkable
class CredentialsProvider(Protocol):
    """Hands out a token for a host. The library never stores or refreshes
    one; the consumer does."""

    def token(self, host: str) -> str | None: ...


class StaticCredentials:
    """A provider over one token, for scripts and tests."""

    def __init__(self, token: str | None) -> None:
        self._token = token

    def token(self, host: str) -> str | None:
        return self._token


@runtime_checkable
class SkillSource(Protocol):
    def resolve(self) -> ResolvedSource: ...


def resolve_tree(
    tree: Mapping[str, bytes],
    *,
    kind: str,
    url: str,
    ref: str | None,
    revision: str,
    subpath: str | None = None,
    full_depth: bool = False,
    limits: Limits = Limits(),
    enforce_directory_name: bool = True,
) -> ResolvedSource:
    """Discover and validate every skill in a tree."""
    skills: list[Skill] = []
    for found in discover(tree, full_depth=full_depth, subpath=subpath):
        bundle = Bundle(found.files)
        text = bundle.text("SKILL.md")
        parsed = fm.parse(text) if text is not None else (None, [])
        directory = found.path.rsplit("/", 1)[-1] if found.path else None
        report = validate_bundle(
            bundle,
            directory_name=directory if enforce_directory_name else None,
            limits=limits,
            parsed=parsed,
        )
        frontmatter = parsed[0]
        skills.append(
            Skill(
                name=frontmatter.name
                if frontmatter and frontmatter.name
                else (directory or ""),
                description=frontmatter.description if frontmatter else "",
                path=found.path,
                container=found.container,
                frontmatter=frontmatter,
                bundle=bundle,
                report=report,
                limits=limits,
            )
        )
    issues: list[Issue] = duplicate_name_issues(s.name for s in skills if s.name)
    return ResolvedSource(
        kind=kind,
        url=url,
        ref=ref,
        revision=revision,
        all_skills=tuple(skills),
        issues=tuple(issues),
    )
