"""Run-scoped catalogs and explicit draft-authoring tools.

The catalog is independent of sandbox availability. Only script execution needs
materialization. Canonical versions are never writable from a sandbox.
"""

import json
from uuid import UUID

from langchain_core.tools import tool

from app.database import AsyncSessionLocal
from app.exceptions import DomainValidationError, NotFoundError
from app.skills.bundles import skill_markdown
from app.skills.schemas import SkillBundle, SkillSave
from app.skills.service import SkillService
from app.users.models import UserDB


async def resolve_skills(
    db, spec, user_id: str, thread_id: str, snapshot: dict | None = None
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
            await service.authorize(binding.skill_id, user)
            version = await service.repository.version(binding.version_id)
            entries.append(
                {
                    "skill_id": str(binding.skill_id),
                    "version_id": str(version.id),
                    "number": version.number,
                    "bundle": version.bundle,
                }
            )
        test = await service.repository.test_for_thread(thread_id)
        if test is not None:
            # Only the selected parent agent receives the test override.
            from app.threads.models import ThreadDB

            thread = await db.get(ThreadDB, thread_id)
            if thread.agent_id == spec.id:
                await service.authorize(test.skill_id, user)
                entries = [
                    e
                    for e in entries
                    if e["skill_id"] != str(test.skill_id)
                    and e["bundle"]["name"] != test.bundle["name"]
                ]
                entries.append(
                    {
                        "skill_id": str(test.skill_id),
                        "version_id": None,
                        "number": "draft-test",
                        "bundle": test.bundle,
                    }
                )
        catalog = {"entries": entries}
    for entry in catalog.get("entries", []):
        bundle = SkillBundle.model_validate(entry["bundle"])
        missing = service.missing(spec, bundle)
        if missing:
            raise DomainValidationError(
                f"Skill {bundle.title} needs: {', '.join(missing)}"
            )
    return catalog


def catalog_tools(catalog: dict):
    entries = {e["bundle"]["name"]: e for e in catalog.get("entries", [])}
    if not entries:
        return []
    manifest = [
        {
            "name": name,
            "description": e["bundle"]["description"],
            "version": e["number"],
        }
        for name, e in entries.items()
    ]

    @tool(
        description="Read a skill's instructions before following its procedure. Available skills: "
        + json.dumps(manifest)
    )
    def read_skill(name: str, path: str = "SKILL.md") -> str:
        """Load an attached skill or one of its supporting text files."""
        if name not in entries:
            return "Skill is not in this agent's catalog."
        bundle = SkillBundle.model_validate(entries[name]["bundle"])
        root = f"/skills/{name}/{bundle.digest()}"
        if path == "SKILL.md":
            return (
                f"Skill ID: {entries[name]['skill_id']}; version: {entries[name]['number']}\n"
                f"Sandbox path after connecting: {root}\n"
                "Copy scripts to your working directory before adapting them. Sandbox edits do not update the saved skill.\n"
                + skill_markdown(bundle)
                + "\n\nFiles:\n"
                + "\n".join(f.path for f in bundle.files)
            )
        file = next((f for f in bundle.files if f.path == path), None)
        if file is None:
            return "File not found in this skill."
        if file.encoding != "utf-8":
            return f"Binary asset available in the sandbox at {root}/{file.path}."
        return file.content

    return [read_skill]


def sandbox_files(catalog: dict) -> list[tuple[str, bytes]]:
    files = []
    for entry in catalog.get("entries", []):
        bundle = SkillBundle.model_validate(entry["bundle"])
        root = f"/skills/{bundle.name}/{bundle.digest()}"
        files.append((f"{root}/SKILL.md", skill_markdown(bundle).encode()))
        files.extend((f"{root}/{file.path}", file.bytes()) for file in bundle.files)
    return files


def authoring_tools(user_id: str):
    # These tools save drafts only. Publication and attachment stay in the UI.
    @tool
    async def list_editable_skills() -> str:
        """List skills you can edit when the user asks to create or improve a skill."""
        async with AsyncSessionLocal() as db:
            user = await db.get(UserDB, UUID(user_id))
            skills = await SkillService(db).list(user)
            return json.dumps(
                [
                    {
                        "id": str(s.id),
                        "name": s.draft.name,
                        "title": s.draft.title,
                        "revision": s.revision,
                    }
                    for s in skills
                    if s.can_edit
                ]
            )

    @tool
    async def read_skill_draft(skill_id: str) -> str:
        """Read the current draft and revision before editing a saved skill."""
        async with AsyncSessionLocal() as db:
            user = await db.get(UserDB, UUID(user_id))
            row = await SkillService(db).authorize(UUID(skill_id), user, edit=True)
            return json.dumps(
                {
                    "revision": row.revision,
                    "visibility": row.visibility,
                    "bundle": row.draft,
                }
            )

    @tool
    async def save_skill_draft(
        bundle: SkillBundle, skill_id: str | None = None, revision: int | None = None
    ) -> str:
        """Save a reusable skill draft ONLY when the user asks to teach/save/improve a skill.

        Capture the reusable procedure, working scripts and examples. Replace
        one-off inputs with parameters; exclude secrets and customer data.
        For edits read_skill_draft first and pass its revision. Include complete
        files (UTF-8 or base64) in the bundle. Never publish automatically.
        """
        async with AsyncSessionLocal() as db:
            user = await db.get(UserDB, UUID(user_id))
            service = SkillService(db)
            visibility = "private"
            if skill_id:
                existing = await service.authorize(UUID(skill_id), user, edit=True)
                visibility = existing.visibility
            result = await service.save(
                SkillSave(bundle=bundle, revision=revision, visibility=visibility),
                user,
                UUID(skill_id) if skill_id else None,
            )
            await db.commit()  # Tool calls own a short transaction outside HTTP.
            return f"Draft saved. Review, test and publish at /skills/{result.id}. Published versions have not changed."

    return [list_editable_skills, read_skill_draft, save_skill_draft]
