"""On-demand skill catalogs and sandbox files. No authoring tools."""

import json
from uuid import UUID

from langchain_core.tools import tool

from app.exceptions import NotFoundError
from app.skills.bundles import skill_markdown
from app.skills.schemas import SkillBundle
from app.skills.service import SkillService
from app.users.models import UserDB


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


def skill_directory(bundle: SkillBundle) -> str:
    """Use sandbox-writable storage, without requiring root permissions."""
    return f"/tmp/auxilia-skills/{bundle.name}/{bundle.digest()}"


def catalog_tools(catalog: dict):
    entries = {e["bundle"]["name"]: e for e in catalog.get("entries", [])}
    if not entries:
        return []
    manifest = [
        {
            "name": name,
            "description": e["bundle"]["description"],
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
        root = skill_directory(bundle)
        if path == "SKILL.md":
            return (
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
        root = skill_directory(bundle)
        files.append((f"{root}/SKILL.md", skill_markdown(bundle).encode()))
        files.extend((f"{root}/{file.path}", file.bytes()) for file in bundle.files)
    return files
