"""The gates a run passes before it exists — one definition each.

Two callers share them: `launch()` (every ingress, before the run row is
inserted) and the worker (`RunWorker._stream`, the net under background
launches that have nobody to answer to). The gates used to be written at
each ingress — three HTTP routers, the trigger service, the worker — in
different subsets; this module is where they live now.

Every gate takes the caller's session and does its DB reads on it. The OAuth
gate also does network IO (token probes, OAuth metadata discovery), so it
commits the session first to release the pooled connection — the one
`db.commit()` outside a request handler, and the reason it is here and not on
a `BaseService`.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.run_spec import RunSpec
from app.mcp.client.connectivity import initiate_oauth, probe_authorization
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.servers.models import MCPAuthType
from app.mcp.servers.repository import MCPServerRepository
from app.model_providers.service import ModelService
from app.sandbox.provider import ensure_sandboxes_available
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)


async def ensure_launchable(db: AsyncSession, thread: ThreadDB) -> RunSpec | None:
    """The availability gates: the thread's pinned model must resolve
    (whitelist ∧ provider key ∧ admin-enabled), else `ModelUnavailableError`;
    and every sandbox its agent graph binds must answer a probe, else
    `SandboxUnavailableError` — a provider outage is a 409 at launch, not a
    failed run the model gets to reason about.

    Returns the `RunSpec` read along the way (None when the agent is gone) so
    the caller can hand it to `required_oauth_url` instead of reading it twice.
    """
    await ModelService(db).ensure_available(thread.model_id)
    spec = await AgentRepository(db).get_run_spec(thread.agent_id)
    if spec is not None:
        await ensure_sandboxes_available(spec.all_sandbox_rows)
    return spec


async def required_oauth_url(
    db: AsyncSession,
    agent_id: UUID,
    user_id: str,
    *,
    spec: RunSpec | None = None,
) -> str | None:
    """The authorize URL a launch needs first, or None.

    None means every OAuth server the agent **or a subagent** binds is
    connected for this user; a URL means the first one that is not, and the
    caller decides what that means — `launch` raises it as
    `OAuthAuthorizationRequired` for the HTTP routers to answer 401
    `{oauth_required, auth_url}`, the worker fails a background run fast, and
    `TriggerService.run_now` rejects with an actionable message.

    It used to *raise* the URL and let an app-global handler turn the
    exception into that 401. Returning it keeps the decision at the call
    site, where the callers already differed (design review §2.4).

    `spec` skips the graph read when the caller already holds it
    (`ensure_launchable` returns it). Auth is per (user, server), so server
    ids are deduped — a server shared by the agent and a subagent is probed
    once.

    Fail-open: if probing or OAuth discovery breaks for infra reasons
    (provider down, no metadata), the run launches and the failure surfaces
    in-thread as before — only a confirmed-unauthorized server blocks.
    """
    if spec is None:
        spec = await AgentRepository(db).get_run_spec(agent_id)
    bindings = spec.all_mcp_bindings if spec is not None else []
    if not bindings:
        return None

    server_ids = {b.mcp_server_id for b in bindings}
    rows = await MCPServerRepository(db).list_by_ids(server_ids)
    servers = [s for s in rows if s.auth_type == MCPAuthType.oauth2]
    # DB reads done — release the pooled connection before the probes'
    # network IO (token refresh, OAuth metadata discovery can take
    # seconds). expire_on_commit=False keeps the loaded rows usable.
    await db.commit()

    # Concurrent, fail-open and memoized — shared with the readiness
    # endpoint, which used to carry a sequential fail-loud copy (§4.1).
    authorized = await probe_authorization(servers, user_id)
    for server in servers:
        if authorized.get(server.id, True):
            continue
        try:
            # Ends in OAuthAuthorizationRequired(auth_url) for the first
            # unauthorized server; the caller connects it and retries.
            await initiate_oauth(server, user_id, db)
        except OAuthAuthorizationRequired as exc:
            return exc.url
        except Exception:  # noqa: BLE001 — fail-open: a probe error must not block the run
            logger.warning(
                "OAuth pre-flight for MCP server %s failed; letting the run launch",
                server.id,
                exc_info=True,
            )
    return None
