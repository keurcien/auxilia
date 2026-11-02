from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from deepagents.backends.sandbox import BaseSandbox
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import ProjectContextFileDB
from app.projects.repository import ProjectRepository
from app.users.models import WorkspaceRole
from app.visibility import ResourceVisibility, is_resource_visible_to_identity
from app.workspaces.repository import WorkspaceRepository
from skillkit.digest import bundle_digest


PROJECT_CONTEXT_ROOT = "/tmp/auxilia-project-context"
PROJECT_CONTEXT_DIGEST = ".auxilia-digest"


def context_file_description(content: str) -> str | None:
    for raw_line in content.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return None


@dataclass(frozen=True)
class ProjectRunContext:
    system_prompt: str
    rows: tuple[ProjectContextFileDB, ...]
    skill_ids: tuple[UUID, ...]

    @property
    def files(self) -> dict[str, bytes]:
        return {
            f"{PROJECT_CONTEXT_ROOT}/{row.path}": row.content.encode("utf-8")
            for row in self.rows
        }

    @property
    def system_context(self) -> str | None:
        sections: list[str] = []
        if self.system_prompt.strip():
            sections.append("## Project instructions\n\n" + self.system_prompt.strip())
        if self.rows:
            lines = [
                "## Project context files",
                "",
                "Read only the files relevant to the current request with `read_file`.",
            ]
            for row in self.rows:
                path = f"{PROJECT_CONTEXT_ROOT}/{row.path}"
                description = context_file_description(row.content)
                lines.append(
                    f"- `{path}`"
                    + (f": {description}" if description is not None else "")
                )
            sections.append("\n".join(lines))
        return "\n\n".join(sections) or None


async def resolve_project_run_context(
    db: AsyncSession,
    workspace_id: UUID,
    project_id: UUID | None,
    user_id: UUID,
) -> ProjectRunContext | None:
    if project_id is None:
        return None
    repository = ProjectRepository(db, workspace_id)
    project = await repository.get(project_id)
    if project is None:
        return None
    membership = await WorkspaceRepository(db).get_membership(workspace_id, user_id)
    if membership is None:
        return None
    team_ids = (
        set(await repository.list_team_ids(project.id))
        if project.visibility == ResourceVisibility.teams
        else set()
    )
    if not is_resource_visible_to_identity(
        visibility=project.visibility,
        owner_id=project.owner_id,
        team_ids=team_ids,
        user_id=user_id,
        is_admin=membership.role == WorkspaceRole.admin,
        team_id=membership.team_id,
    ):
        return None
    return ProjectRunContext(
        system_prompt=project.system_prompt,
        rows=tuple(await repository.list_context_files(project.id)),
        skill_ids=tuple(await repository.list_skill_ids(project.id)),
    )


def upload_project_context(backend: BaseSandbox, files: dict[str, bytes]) -> bool:
    marker = f"{PROJECT_CONTEXT_ROOT}/{PROJECT_CONTEXT_DIGEST}"
    if not files:
        removed = backend.execute(
            f"rm -rf {shlex.quote(PROJECT_CONTEXT_ROOT)}"
        )  # nosemgrep
        if removed.exit_code != 0:
            raise RuntimeError(
                "Failed to remove project context from the sandbox: "
                f"{removed.output[:2000]}"
            )
        return False

    digest = bundle_digest(files)
    current = backend.execute(f"cat {shlex.quote(marker)} 2>/dev/null")  # nosemgrep
    if current.exit_code == 0 and current.output.strip() == digest:
        return False

    directories = sorted({str(PurePosixPath(path).parent) for path in files})
    created = backend.execute(  # nosemgrep
        f"rm -rf {shlex.quote(PROJECT_CONTEXT_ROOT)} && mkdir -p "
        + " ".join(shlex.quote(directory) for directory in directories)
    )
    if created.exit_code != 0:
        raise RuntimeError(
            f"Failed to create project context in the sandbox: {created.output[:2000]}"
        )
    _upload_or_raise(backend, list(files.items()), "project context files")
    _upload_or_raise(
        backend,
        [(marker, digest.encode())],
        "the project context digest marker",
    )
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
