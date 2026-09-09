"""deepagents' ``SkillsMiddleware``, configured for this app.

A leaf module (deepagents only) so ``app/agents/harness.py`` can import it
without pulling in the skills service layer.
"""

from __future__ import annotations

import base64

from deepagents.backends import StateBackend
from deepagents.backends.protocol import BackendProtocol, FileData
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemState
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents.middleware.types import AgentMiddleware


# deepagents' template, minus its sentence about "Deepagents" vs "Agents"
# sources (a Claude-Code-ism) and with the sandbox caveat this app needs. The
# three slots are the middleware's contract.
SKILLS_SYSTEM_PROMPT = """## Skills

Reusable procedures attached to you. Each is a folder with a SKILL.md and \
optional scripts or reference files.

{skills_locations}{skills_load_warnings}

**Available skills:**

{skills_list}

Use a skill when the user's request matches its description. Read its \
SKILL.md first with `read_file(file_path="...", limit=1000)`, then follow \
it. Supporting files live next to it; run scripts by their absolute path. \
Copy a script before changing it — edits inside the sandbox do not change \
the saved skill."""


class FreshSkillsMiddleware(SkillsMiddleware):
    """``SkillsMiddleware`` that re-reads the skill index on every run.

    The base class loads the index once and keeps it in checkpointed state,
    so a skill saved between two turns of a thread would never be re-listed.
    Here the run snapshot is rebuilt per run and the files with it, so the
    index is rebuilt too: a save reaches every agent on its next run.
    """

    @property
    def name(self) -> str:
        # The registered name is the slot: deepagents matches overrides and
        # langchain de-duplicates by it, so this *is* the SkillsMiddleware.
        return "SkillsMiddleware"

    def __init__(self, *, backend: BackendProtocol, sources) -> None:
        super().__init__(
            backend=backend, sources=sources, system_prompt=SKILLS_SYSTEM_PROMPT
        )

    def before_agent(self, state, runtime, config):
        return super().before_agent(_without_index(state), runtime, config)

    async def abefore_agent(self, state, runtime, config):
        return await super().abefore_agent(_without_index(state), runtime, config)


def _without_index(state):
    return {key: value for key, value in state.items() if key != "skills_metadata"}


class SkillFilesMiddleware(AgentMiddleware):
    """Put an agent's skill files into its graph state before each run.

    For an agent without a sandbox the "filesystem" is the checkpointed
    ``files`` channel that deepagents' ``StateBackend`` reads: no host
    directory, no process, nothing outside the agent's own state. This hook
    runs first, so ``SkillsMiddleware`` finds the files when it builds the
    index one node later.

    The update is a diff against what the thread already holds: unchanged
    files are not rewritten (the channel is a delta log, so that keeps
    checkpoints small across turns), a file that changed or appeared is
    written, and a path under this agent's root that is no longer part of a
    skill is removed (``None`` deletes in the files reducer). A resume does
    not re-run this hook, which matches the run snapshot being reused.
    """

    state_schema = FilesystemState

    def __init__(self, root: str, files: list[tuple[str, bytes]]) -> None:
        super().__init__()
        self.root = root
        self.desired: dict[str, FileData] = {
            path: _file_data(content) for path, content in files
        }

    def before_agent(self, state, runtime, config):
        current = state.get("files") or {}
        update: dict[str, FileData | None] = {}
        for path, data in self.desired.items():
            existing = current.get(path)
            if existing is None or not _same_content(existing, data):
                update[path] = data
        prefix = self.root.rstrip("/") + "/"
        for path in current:
            if path.startswith(prefix) and path not in self.desired:
                update[path] = None
        return {"files": update} if update else None


def _file_data(content: bytes) -> FileData:
    try:
        return create_file_data(content.decode("utf-8"))
    except UnicodeDecodeError:
        return create_file_data(
            base64.b64encode(content).decode("ascii"), encoding="base64"
        )


def _same_content(existing: FileData, desired: FileData) -> bool:
    return (
        existing.get("content") == desired["content"]
        and existing.get("encoding", "utf-8") == desired["encoding"]
    )


def skills_read_middleware(
    root: str, files: list[tuple[str, bytes]], sources
) -> list[AgentMiddleware]:
    """Skills for an agent without a sandbox: the files live in agent state,
    the index is rebuilt from them, and the agent gets only the two read
    tools over that state — a way to read its skills, not a filesystem and
    not a process anywhere."""
    backend = StateBackend()
    return [
        SkillFilesMiddleware(root, files),
        FreshSkillsMiddleware(backend=backend, sources=sources),
        FilesystemMiddleware(
            backend=backend,
            tools=["ls", "read_file"],
            tool_token_limit_before_evict=None,
            human_message_token_limit_before_evict=None,
        ),
    ]
