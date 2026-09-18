"""Skills at run time: the frozen set, its in-memory view, and its upload.

There is no custom skill tool. deepagents' ``SkillsMiddleware`` (subclassed in
``app/skills/middleware.py``) lists the skills in the system prompt and the
agent reads them with the filesystem ``read_file`` tool. This module's job is
to produce what that needs from a run's frozen bundles:

- ``SkillsBackend`` — a read-only, in-memory backend holding every file under
  ``SKILLS_ROOT/<name>/``. The index is always read from it; a sandbox-less
  agent's ``ls`` / ``read_file`` too. Nothing is written to any disk or to the
  checkpoint.
- ``upload_skills`` — the same files on a sandbox's disk, so scripts can run;
  skipped when the sandbox already holds this exact set.
- ``freeze_run_skills`` — which bundles a run executes with, frozen on the
  thread so a resume never swaps skill contents under a pending tool call.

One skill set per graph: a supervisor and its subagents share the union of
their enabled skills, so any of them can read or run any skill file by the
same absolute path.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from pathlib import PurePosixPath
from uuid import UUID

from deepagents.backends.sandbox import BaseSandbox
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DomainValidationError
from app.skills.middleware import SKILLS_ROOT
from app.skills.repository import SkillRepository
from app.skills.schemas import SkillBundle
from app.threads.models import ThreadDB
from skillkit.adapters.deepagents import (
    READ_ONLY,
    InMemorySkillsBackend,
    skill_files as _flatten,
)
from skillkit.digest import bundle_digest


# Written next to the skills in a sandbox; holds the digest of what is there.
DIGEST_MARKER = ".auxilia-digest"
__all__ = [
    "READ_ONLY",
    "SkillsBackend",
    "skill_files",
    "skills_digest",
    "upload_skills",
]


async def freeze_run_skills(
    db: AsyncSession, thread: ThreadDB, agent_ids: Iterable[UUID], *, resume: bool
) -> list[SkillBundle]:
    """The skills this run executes with.

    A new turn resolves the graph's current skills and stamps them on the
    thread — the caller's transaction writes the stamp. A resume reuses the
    stamped set, so approving a tool call never swaps the skill it came from,
    even if the skill was saved or disabled meanwhile. `agent_ids` are the
    graph's members: a supervisor and its subagents share one skill set.

    Access is not re-checked on a resume because there is nothing to check:
    every workspace user may use every skill, so a frozen copy grants nothing
    its reader lacked.
    """
    if resume and thread.skill_snapshot is not None:
        return [SkillBundle.model_validate(entry) for entry in thread.skill_snapshot]
    rows = await SkillRepository(db).list_for_agents(agent_ids)
    bundles = [row.to_bundle() for row in rows]
    ensure_unique_names(bundles)
    thread.skill_snapshot = [bundle.model_dump(mode="json") for bundle in bundles]
    return bundles


def ensure_unique_names(bundles: Iterable[SkillBundle]) -> None:
    """The model addresses a skill by name and its files by
    ``SKILLS_ROOT/<name>/``, so two skills of one name cannot share a run.
    Refused when it would arise (`SkillService`); hitting it here means the
    data changed under a run — fail it rather than silently drop one."""
    seen: set[str] = set()
    for bundle in bundles:
        if bundle.name in seen:
            raise DomainValidationError(
                f"Two different skills named '{bundle.name}' are enabled on this "
                "agent's graph; disable one before running."
            )
        seen.add(bundle.name)


def skill_files(bundles: Iterable[SkillBundle]) -> dict[str, bytes]:
    """Every file of every skill, keyed by its absolute path — the layout
    ``SkillsMiddleware`` scans: ``SKILLS_ROOT/<name>/SKILL.md`` plus files."""
    return _flatten(
        {bundle.name: bundle.file_bytes() for bundle in bundles}, SKILLS_ROOT
    )


class SkillsBackend(InMemorySkillsBackend):
    """The run's read-only, in-memory view of its skill files (skillkit's
    ``InMemorySkillsBackend`` over ``skill_files``). Nothing lands in the
    checkpoint; it works outside a graph context; every write is refused."""

    def __init__(self, bundles: Iterable[SkillBundle]) -> None:
        super().__init__(skill_files(bundles))


def skills_digest(files: dict[str, bytes]) -> str:
    """Content hash of a skill set, path and bytes (skillkit's digest over
    the flattened tree)."""
    return bundle_digest(files)


def upload_skills(backend: BaseSandbox, files: dict[str, bytes]) -> bool:
    """Put the run's skill files on the sandbox disk, if they are not there.

    A marker file under the root records the digest of what was uploaded, so
    a reconnected sandbox that already holds the current set costs one `cat`.
    When the digest differs (new sandbox, or a skill changed since) the root
    is recreated from scratch — a file removed from a skill must not linger —
    and everything is uploaded. With no skills the root is removed. Returns
    whether an upload happened. Any failure raises: a sandboxed agent is
    expected to have its skills, and a half-written skill is worse than a
    failed run.
    """
    # `backend` is a *sandbox*, and `execute` runs a shell command — semgrep's
    # SQLAlchemy rules match the method name, not the receiver, and read these
    # as raw queries. Every interpolation is either a module constant or passed
    # through `shlex.quote`; there is no database anywhere near this function.
    marker = f"{SKILLS_ROOT}/{DIGEST_MARKER}"
    if not files:
        # Checked like every other step: a failed removal leaves the previous
        # run's skills on disk, and the model would go on reading them.
        removed = backend.execute(f"rm -rf {shlex.quote(SKILLS_ROOT)}")  # nosemgrep
        if removed.exit_code != 0:
            raise RuntimeError(
                "Failed to remove the skills directory from the sandbox: "
                f"{removed.output[:2000]}"
            )
        return False
    digest = skills_digest(files)
    current = backend.execute(f"cat {shlex.quote(marker)} 2>/dev/null")  # nosemgrep
    if current.exit_code == 0 and current.output.strip() == digest:
        return False
    directories = sorted({str(PurePosixPath(path).parent) for path in files})
    created = backend.execute(  # nosemgrep
        f"rm -rf {shlex.quote(SKILLS_ROOT)} && mkdir -p "
        + " ".join(shlex.quote(directory) for directory in directories)
    )
    if created.exit_code != 0:
        raise RuntimeError(
            f"Failed to create the skills directory in the sandbox: {created.output[:2000]}"
        )
    # Two phases, and the order matters. Backends report a failed file and
    # carry on with the rest, so a marker written in the same batch could
    # land while a script did not: the next run's digest check would match,
    # return early, and never repair the missing file. The marker goes last,
    # once every skill file is known to be there — a run that fails between
    # the two leaves no marker, so the next one re-uploads everything.
    _upload_or_raise(backend, list(files.items()), "skill files")
    _upload_or_raise(backend, [(marker, digest.encode())], "the digest marker")
    return True


def _upload_or_raise(
    backend: BaseSandbox, uploads: list[tuple[str, bytes]], what: str
) -> None:
    results = backend.upload_files(uploads)
    failed = [result.path for result in results if result.error]
    if failed or len(results) != len(uploads):
        raise RuntimeError(
            f"Failed to upload {what} to the sandbox: "
            + (", ".join(failed) or "incomplete upload")
        )
