"""Stage 2 of executing a run: bind the live resources a turn needs.

`open_resources(resolved)` is the network stage. For the length of one turn
it holds the checkpointer, one open MCP connection context per server (see
`Toolset.open` — whether a server is stateful or stateless is that module's
business), and the run's sandbox with the skill files on it. It yields
`LiveResources`: handles plus *facts* about them (which sandbox was opened,
whether it replaced a lost one). It writes nothing to the database — the
worker, which owns persistence, stamps the thread from those facts.

Leaving the context persists the sandbox (Cloud Run sandboxes export their
overlay to GCS for cross-instance reconnects; OpenSandbox's persist is a
no-op) and closes everything, whichever way the turn ended.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from app.database import get_checkpointer
from app.runtime.resolve import ResolvedAgent, ResolvedRun
from app.runtime.toolset import Toolset
from app.sandbox.provider import SandboxSession, open_sandbox
from app.skills.runtime import skill_files, upload_skills


logger = logging.getLogger(__name__)


@dataclass
class LiveResources:
    """What `open_resources` holds open for one turn."""

    checkpointer: object
    toolsets: dict[UUID, Toolset] = field(default_factory=dict)
    # The run's one live sandbox, shared by the parent and every
    # sandbox-bound subagent; None when no member is bound to one.
    sandbox: SandboxSession | None = None
    # The sandbox row that issued `sandbox.sandbox_id` — stamped on the
    # thread next to the id so a later run knows whether to reconnect.
    sandbox_source_id: UUID | None = None

    def tools_for(self, agent: ResolvedAgent) -> list:
        """The agent's tools, bound to this turn's live connections."""
        return self.toolsets[agent.config.id].all

    def sandbox_backend_for(self, agent: ResolvedAgent):
        """The live sandbox backend, for an agent bound to one; else None."""
        if self.sandbox is None or agent.sandbox is None:
            return None
        return self.sandbox.backend

    def sandbox_stamp(self, thread) -> tuple[str, UUID | None] | None:
        """What the thread should remember about this turn's sandbox —
        `(sandbox_id, source_id)` — or None when it already does. The worker
        writes it; this stage only decides."""
        if self.sandbox is None or self.sandbox.sandbox_id == thread.sandbox_id:
            return None
        return self.sandbox.sandbox_id, self.sandbox_source_id

    @property
    def sandbox_replaced(self) -> bool:
        """True when the thread's remembered sandbox was gone and a fresh,
        empty one was created in its place — the model is told once."""
        return self.sandbox is not None and self.sandbox.replaced


@asynccontextmanager
async def open_resources(resolved: ResolvedRun) -> AsyncIterator[LiveResources]:
    """Open the turn's MCP connections, checkpointer and sandbox; yield the
    handles; persist and close on the way out."""
    async with AsyncExitStack() as stack, get_checkpointer() as checkpointer:
        # Open every toolset (parent + subagents) concurrently.
        # return_exceptions=True so all enters finish before we proceed or
        # raise — a bare gather would orphan in-flight connection opens past
        # the stack's unwind on first failure.
        results = await asyncio.gather(
            *(
                stack.enter_async_context(Toolset.open(agent.prepared))
                for agent in resolved.members
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        toolsets = {
            agent.config.id: toolset
            for agent, toolset in zip(resolved.members, results, strict=True)
        }
        sandbox, source_id = await _open_sandbox(resolved)
        try:
            yield LiveResources(
                checkpointer=checkpointer,
                toolsets=toolsets,
                sandbox=sandbox,
                sandbox_source_id=source_id,
            )
        finally:
            await _persist_sandbox(sandbox)


async def _open_sandbox(
    resolved: ResolvedRun,
) -> tuple[SandboxSession | None, UUID | None]:
    """Connect (or create) the thread's sandbox and put the run's skill files
    on it — before the graph runs, so the model only ever sees a live
    filesystem. Returns the session and the sandbox row that issued it.

    One sandbox per run, shared by the parent and every sandbox-bound
    subagent (the first bound member's provider); the thread remembers its
    id so the next run reconnects to the same files. A sandbox that is gone
    is replaced (`SandboxSession.replaced`, which the turn turns into a host
    notice); any other failure fails the run as `SandboxUnavailableError`.
    Provider calls are blocking SDK calls, run off the loop.
    """
    bound = [agent for agent in resolved.members if agent.sandbox is not None]
    if not bound:
        return None, None
    source = bound[0].sandbox
    assert source is not None  # narrowed by the filter above
    thread = resolved.thread
    # Reconnect only to an id this sandbox row issued. After a rebinding the
    # stored id belongs to the previous provider, which cannot know it —
    # reconnecting failed the run instead of starting a fresh sandbox. A null
    # source means the thread was stamped before that column existed — still
    # this sandbox, as far as anything knows, so it reconnects. Deleting a
    # sandbox row clears the thread's stamp outright (`SandboxService`), so
    # null never means "the issuer was deleted".
    previous = (
        thread.sandbox_id if thread.sandbox_source_id in (None, source.row_id) else None
    )
    session = await asyncio.to_thread(open_sandbox, source.provider, previous)
    await asyncio.to_thread(
        upload_skills, session.backend, skill_files(resolved.skills)
    )
    return session, source.row_id


async def _persist_sandbox(sandbox: SandboxSession | None) -> None:
    """Snapshot the sandbox state at turn end, if one was used. Failures are
    logged, never raised — a snapshot problem must not mask the run's
    result."""
    if sandbox is None:
        return
    try:
        await asyncio.to_thread(sandbox.persist)
    except Exception:
        logger.exception("Failed to persist sandbox state")
