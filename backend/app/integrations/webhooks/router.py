import hmac
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from langchain.messages import HumanMessage
from pydantic import BaseModel, Field

from app.agents.runtime import AgentRuntime, build_agent_deps
from app.database import AsyncSessionLocal
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.settings import app_settings
from app.threads.models import ThreadDB
from app.users.models import UserDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookInvokeRequest(BaseModel):
    agent_id: str
    message: str = Field(max_length=10_000)
    model_id: str | None = None


async def _run_agent(thread: ThreadDB, message: str) -> None:
    """Drain the agent stream in background, discarding output."""
    async with AsyncSessionLocal() as db:
        deps = build_agent_deps(thread, db)
        try:
            agent_runtime = await AgentRuntime.create(thread=thread, db=db, deps=deps)
            # Use the slack adapter (yields plain Python dicts) instead of ai_sdk
            # (yields SSE strings for browsers). We only need to drain the stream to
            # trigger agent execution and catch errors — no output is forwarded.
            async for ev in agent_runtime.stream(
                messages=[HumanMessage(content=message)],
                stream_adapter="slack",
            ):
                if ev.get("type") == "error":
                    logger.error("Webhook agent error: %s", ev.get("content"))
        except OAuthAuthorizationRequired as exc:
            logger.error(
                "Webhook: OAuth re-authorization required for thread %s — %s",
                thread.id,
                exc.url,
            )
        except Exception:
            logger.exception("Webhook: unexpected error for thread %s", thread.id)


@router.post("/invoke")
async def webhook_invoke(
    payload: WebhookInvokeRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(default=None),
) -> dict:
    if not app_settings.webhook_secret or not app_settings.webhook_user_id:
        raise HTTPException(status_code=503, detail="Webhooks not configured")

    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, app_settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    async with AsyncSessionLocal() as db:
        user = await db.get(UserDB, app_settings.webhook_user_id)
        if not user:
            raise HTTPException(status_code=503, detail="Webhook user not found")

        from app.agents.models import AgentDB
        agent = await db.get(AgentDB, payload.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        thread = ThreadDB(
            id=str(uuid4()),
            agent_id=payload.agent_id,
            user_id=app_settings.webhook_user_id,
            model_id=payload.model_id or agent.model_id,
            first_message_content=payload.message,
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        thread_id = thread.id

    background_tasks.add_task(_run_agent, thread, payload.message)

    return {"thread_id": thread_id, "agent_id": payload.agent_id}
