"""Skills at run time: frozen bundles become files the agent reads through
deepagents' ``SkillsMiddleware``.

There is no custom skill tool. The middleware (``app/skills/middleware.py``)
appends the skill index to the system prompt and the agent reads a skill with
the filesystem ``read_file`` tool, the way every deepagents agent does. This
module's job is to put the files where the middleware looks — ``SKILLS_ROOT``
on the backend the agent's filesystem tools use: the run's live sandbox, or
(``SkillFilesMiddleware``) the agent's own graph state for an agent without one.

One skill set per graph: a supervisor and its subagents share the union of
their attached skills (``merge_catalogs``), so any of them can read or run any
skill file by the same absolute path. Two different skills with the same name
in one graph are refused when they would be attached or when the graph is
assembled (``SkillService.ensure_no_name_collision``); the merge here is the
last line of defence and fails the run rather than pick one.
"""

from __future__ import annotations

import hashlib
import shlex
from collections.abc import Iterable
from pathlib import PurePosixPath
from uuid import UUID

from deepagents.backends.sandbox import BaseSandbox

from app.exceptions import DomainValidationError, NotFoundError
from app.skills.bundles import skill_markdown
from app.skills.schemas import SkillBundle
from app.skills.service import SkillService
from app.users.models import UserDB


# Sandbox-writable without root; the same virtual path serves the local copy.
SKILLS_ROOT = "/tmp/auxilia-skills"
# Written next to the skills; holds `skills_digest` of what the sandbox has.
DIGEST_MARKER = ".auxilia-digest"


async def resolve_skills(
    db, spec, user_id: str, _thread_id: str, snapshot: dict | None = None
):
    service = SkillService(db)
    user = await db.get(UserDB, UUID(user_id))
    if user is None:
        raise NotFoundError("User not found")
    if snapshot is not None:
        catalog = snapshot
        # Recheck access on retries/resume; never let a saved snapshot grant access.
        for entry in catalog.get("entries", []):
            await service.authorize(UUID(entry["skill_id"]), user)
    else:
        entries = []
        for binding in await service.repository.bindings(agent_id=spec.id):
            row = await service.authorize(binding.skill_id, user)
            entries.append({"skill_id": str(row.id), "bundle": row.bundle})
        catalog = {"entries": entries}
    return catalog


def merge_catalogs(catalogs: Iterable[dict]) -> dict:
    """The graph's one catalog: the union of its agents' skills by id.

    The same skill attached to two agents is one entry. Two *different* skills
    with the same name cannot coexist, because the model addresses a skill by
    name and the files by ``SKILLS_ROOT/<name>/``; that is refused when it
    would arise, so hitting it here means the data changed under a run — fail
    it rather than silently drop one.
    """
    entries: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for catalog in catalogs:
        for entry in catalog.get("entries", []):
            skill_id = str(entry["skill_id"])
            name = entry["bundle"]["name"]
            if by_name.get(name, skill_id) != skill_id:
                raise DomainValidationError(
                    f"Two different skills named '{name}' are attached to agents "
                    "of this graph; detach one before running."
                )
            by_name[name] = skill_id
            entries.setdefault(skill_id, entry)
    return {"entries": list(entries.values())}


def skills_sources(catalog: dict) -> list[tuple[str, str]] | None:
    """``SkillsMiddleware`` sources — ``None`` when the graph has no skills,
    which (as in ``create_deep_agent``) means no middleware and no prompt
    fragment at all."""
    if not catalog.get("entries"):
        return None
    return [(SKILLS_ROOT, "Agent")]


def skill_files(catalog: dict, root: str) -> list[tuple[str, bytes]]:
    """Every file of every skill in the catalog, as ``(path, bytes)`` under
    ``root/<skill-name>/`` — the layout ``SkillsMiddleware`` scans."""
    files = []
    for entry in catalog.get("entries", []):
        bundle = SkillBundle.model_validate(entry["bundle"])
        base = f"{root}/{bundle.name}"
        files.append((f"{base}/SKILL.md", skill_markdown(bundle).encode()))
        files.extend((f"{base}/{file.path}", file.bytes()) for file in bundle.files)
    return files


def skills_digest(files: list[tuple[str, bytes]]) -> str:
    """Content hash of one agent's skill files, path and bytes."""
    digest = hashlib.sha256()
    for path, content in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def materialize_skills(
    backend: BaseSandbox, root: str, files: list[tuple[str, bytes]]
) -> bool:
    """Put one agent's skill files in its sandbox, if they are not there yet.

    A marker file under the root records the digest of what was uploaded, so
    a reconnected sandbox that already holds the current skills costs one
    `cat`. When the digest differs (new sandbox, or a skill was saved since)
    the root is recreated from scratch — a file removed from a skill must not
    linger — and everything is uploaded. Returns whether an upload happened.
    A failure raises: a sandbox agent is expected to have its skills, and a
    half-written skill is worse than a failed run.
    """
    marker = f"{root}/{DIGEST_MARKER}"
    if not files:
        backend.execute(f"rm -rf {shlex.quote(root)}")
        return False
    digest = skills_digest(files)
    current = backend.execute(f"cat {shlex.quote(marker)} 2>/dev/null")
    if current.exit_code == 0 and current.output.strip() == digest:
        return False
    directories = sorted({str(PurePosixPath(path).parent) for path, _ in files})
    command = f"rm -rf {shlex.quote(root)} && mkdir -p " + " ".join(
        shlex.quote(directory) for directory in directories
    )
    created = backend.execute(command)
    if created.exit_code != 0:
        raise RuntimeError(
            "Failed to create sandbox skill directories "
            f"(exit code {created.exit_code}): {created.output[:2000]}"
        )
    uploads = [*files, (marker, digest.encode())]
    results = backend.upload_files(uploads)
    failed = [result.path for result in results if result.error]
    if len(results) != len(uploads) or failed:
        raise RuntimeError(
            "Failed to materialize skill files in sandbox: "
            + (", ".join(failed) or "incomplete upload")
        )
    return True
