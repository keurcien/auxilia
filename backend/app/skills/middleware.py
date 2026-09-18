"""deepagents' ``SkillsMiddleware``, configured for this app.

A leaf module (deepagents only) so ``app/agents/harness.py`` can import it
without pulling in the skills service layer.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillMetadata, SkillsMiddleware


# Where every skill of a run lives, on the sandbox disk and in the read-only
# view a sandbox-less agent gets: ``<root>/<skill-name>/SKILL.md`` plus files.
# The same absolute path in both, so a supervisor can hand a script's path to
# a sandboxed subagent. ``/tmp`` because it is writable without root in every
# sandbox image.
SKILLS_ROOT = "/tmp/auxilia-skills"  # nosec B108 - deliberate, see above
SKILLS_SOURCES: list[tuple[str, str]] = [(SKILLS_ROOT, "Agent")]

# deepagents' template, minus its sentence about "Deepagents" vs "Agents"
# sources (a Claude-Code-ism) and with the sandbox caveat this app needs. The
# three slots are the middleware's contract.
SKILLS_PROMPT = """## Skills

Reusable procedures attached to you. Each is a folder with a SKILL.md and \
optional scripts or reference files.

{skills_locations}{skills_load_warnings}

**Available skills:**

{skills_list}

Use a skill when the user's request matches its description. Read its \
SKILL.md first with `read_file(file_path="...", limit=1000)`, then follow \
it. Its files are listed above with their absolute paths — run a script by \
that path, no need to list the folder first. Copy a script before changing \
it — edits inside the sandbox do not change the saved skill."""

# The variant for an agent without code execution: same disclosure, but the
# scripts can only run somewhere else. The files are also present, at the same
# absolute paths, in the sandbox of any subagent this agent delegates to.
SKILLS_PROMPT_READ_ONLY = SKILLS_PROMPT.replace(
    "Its files are listed above with their absolute paths — run a script by "
    "that path, no need to list the folder first. Copy a script before changing "
    "it — edits inside the sandbox do not change the saved skill.",
    "Its files are listed above with their absolute paths. You cannot run "
    "scripts yourself: if you have a subagent with code execution, delegate the "
    "run to it and give it the script's absolute path — the same path exists in "
    "its sandbox.",
)

# How many of a skill's files the index names before it says "+N more". A
# skill can hold 100 files; the index is a table of contents, not a tree.
INDEX_FILES_MAX = 20


class FreshSkillsMiddleware(SkillsMiddleware):
    """``SkillsMiddleware`` that re-reads the skill index on every run.

    The base class loads the index once and keeps it in checkpointed state,
    so a skill saved or enabled between two turns of a thread would never be
    re-listed. Here the run's skill set is frozen per run and the index is
    rebuilt from it, so a change reaches every agent on its next run.
    """

    @property
    def name(self) -> str:
        # The registered name is the slot: deepagents matches overrides and
        # langchain de-duplicates by it, so this *is* the SkillsMiddleware.
        return "SkillsMiddleware"

    def before_agent(self, state, runtime, config):
        return super().before_agent(_without_index(state), runtime, config)

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """deepagents' lines per skill, plus one naming the skill's files by
        absolute path. The model then reads the SKILL.md and runs a script in
        two calls instead of listing the folder tree first — and a SKILL.md
        that names a file loosely (``python new-script.py``) still resolves."""
        lines = super()._format_skills_list(skills).split("\n")
        out: list[str] = []
        by_path = {skill["path"]: skill for skill in skills}
        for line in lines:
            out.append(line)
            skill = _skill_of_read_line(line, by_path)
            if skill is not None and (files := self._skill_files(skill["path"])):
                out.append(f"  -> Files: {files}")
        return "\n".join(out)

    def _skill_files(self, skill_md_path: str) -> str:
        folder = str(PurePosixPath(skill_md_path).parent)
        result = self._backend.glob("*", path=folder)
        if result.error or not result.matches:
            return ""
        paths = sorted(
            info["path"]
            for info in result.matches
            if not info.get("is_dir") and info["path"] != skill_md_path
        )
        shown = ", ".join(f"`{path}`" for path in paths[:INDEX_FILES_MAX])
        if len(paths) > INDEX_FILES_MAX:
            shown += f" (+{len(paths) - INDEX_FILES_MAX} more, `ls {folder}`)"
        return shown

    async def abefore_agent(self, state, runtime, config):
        return await super().abefore_agent(_without_index(state), runtime, config)


def _without_index(state):
    return {key: value for key, value in state.items() if key != "skills_metadata"}


def _skill_of_read_line(line: str, by_path: dict[str, SkillMetadata]):
    """The skill whose "Read `<path>` for full instructions" line this is."""
    if not line.startswith("  -> Read `"):
        return None
    path = line.removeprefix("  -> Read `").split("`", 1)[0]
    return by_path.get(path)


def skills_index_middleware(
    skills: BackendProtocol, *, sandbox: bool
) -> FreshSkillsMiddleware:
    """The prompt fragment listing the run's skills, read from ``skills`` —
    the in-memory view of the frozen set, never the sandbox disk (the index
    is the same by construction, and this costs no sandbox round trip)."""
    return FreshSkillsMiddleware(
        backend=skills,
        sources=SKILLS_SOURCES,
        system_prompt=SKILLS_PROMPT if sandbox else SKILLS_PROMPT_READ_ONLY,
    )


def skills_read_middleware(skills: BackendProtocol) -> list:
    """Skills for an agent without a sandbox: the index, plus the two read
    tools over the same in-memory view — a way to read its skills, not a
    filesystem and not a process anywhere. No host disk, no checkpointed
    files: the view is rebuilt from the run's frozen set each time."""
    return [
        skills_index_middleware(skills, sandbox=False),
        FilesystemMiddleware(
            backend=skills,
            tools=["ls", "read_file"],
            # Evictions write to the backend; a read-only one has nowhere to put them.
            tool_token_limit_before_evict=None,
            human_message_token_limit_before_evict=None,
        ),
    ]
