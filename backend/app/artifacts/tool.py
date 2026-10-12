"""Run-bound publication tool. Payloads stay out of model context/checkpoints."""

from typing import Annotated
from uuid import UUID

from deepagents.backends.sandbox import BaseSandbox
from langchain_core.tools import InjectedToolCallId, tool

from app.artifacts.schemas import PresentFile
from app.artifacts.service import ArtifactService
from app.database import AsyncSessionLocal


def present_files_tool(backend: BaseSandbox, thread_id: str, sandbox_source_id: UUID):
    @tool(response_format="content_and_artifact")
    async def present_files(
        files: list[PresentFile], tool_call_id: Annotated[str, InjectedToolCallId]
    ):
        """Show finished files in the chat artifact panel. Save deliverables under
        /workspace, /mnt/data or /tmp, then pass their absolute paths and optional
        titles. Supports PPTX, PDF, UTF-8 CSV/Markdown and self-contained HTML.
        Publishes immutable snapshots; call again to present a revision. Without
        configured object storage, files expire with the execution sandbox.
        """
        if not 1 <= len(files) <= 10:
            raise ValueError("Present between 1 and 10 files at a time")
        items = []
        for file in files:
            # Out-of-request: publication commits before its tool result is emitted.
            async with AsyncSessionLocal() as db:
                item = await ArtifactService(db).publish(
                    thread_id=thread_id,
                    tool_call_id=tool_call_id,
                    file=file,
                    backend=backend,
                    sandbox_source_id=sandbox_source_id,
                )
                await db.commit()
                items.append(item.model_dump(mode="json"))
        return {
            "files": [
                {"id": x["id"], "title": x["title"], "temporary": x["temporary"]}
                for x in items
            ]
        }, {"auxilia_artifacts": items}

    return present_files
