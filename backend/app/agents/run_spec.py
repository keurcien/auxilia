"""The narrow read the run path needs — everything, and only, what it takes to
build an agent graph.

`AgentService.get` assembles an `AgentResponse`: owner names, tag names,
permission resolution, sandbox display fields, `is_subagent` flags. That is the
right shape for the API and the wrong shape for a run, which needs
`instructions` + MCP bindings + subagents and nothing else. Resolving a graph
through `get` cost one full assembly *per agent* — and the same graph was
resolved three times per send (readiness poll, run preflight, worker build), so
the waste multiplied by three (design review §1.2 / §2.2).

`RunSpec` is that narrow read, filled by `AgentRepository.get_run_spec` in three
flat queries for a graph of any width. It carries DB rows rather than response
DTOs on purpose: the runtime should not depend on API response assembly, and a
row already holds every field the runtime touches.
"""

from dataclasses import dataclass
from uuid import UUID

from app.agents.models import AgentMCPServerDB, ToolStatus
from app.sandbox.models import SandboxDB


@dataclass(frozen=True)
class SandboxSpec:
    """A resolved agent↔sandbox binding: the sandbox row plus the binding's
    per-tool map. Carrying `row` is what lets the runtime skip the re-fetch it
    used to do for a row the same read had already joined."""

    row: SandboxDB
    tools: dict[str, ToolStatus] | None


@dataclass(frozen=True)
class AgentSpec:
    """One agent's run-relevant state. Used for both the parent and subagents —
    `Agent.build` treats them identically apart from `apply_ui`."""

    id: UUID
    name: str
    instructions: str
    description: str | None
    mcp_servers: list[AgentMCPServerDB]
    sandbox: SandboxSpec | None


@dataclass(frozen=True)
class RunSpec:
    """A parent agent and its direct subagents.

    One level only, matching `Agent.build`, which does not recurse into a
    subagent's own subagents.
    """

    agent: AgentSpec
    subagents: list[AgentSpec]

    @property
    def all_mcp_bindings(self) -> list[AgentMCPServerDB]:
        """Every MCP binding a run of this agent touches: the agent's own plus
        each direct subagent's.

        NOT deduped: `tools` (configuration state) is per binding, so a server
        configured on the parent but left unconfigured on a subagent must stay
        visible to the readiness check. Callers doing per-server work (the OAuth
        probe) dedupe by `mcp_server_id` themselves.
        """
        bindings = list(self.agent.mcp_servers)
        for sub in self.subagents:
            bindings.extend(sub.mcp_servers)
        return bindings
