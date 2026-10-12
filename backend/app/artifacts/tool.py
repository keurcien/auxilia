"""Run-bound publication tool. Payloads stay out of model context/checkpoints."""

import json
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
        /tmp (e.g. /tmp/report.pptx), then pass their absolute paths and optional
        titles. Supports PPTX, PDF, UTF-8 CSV/Markdown and self-contained HTML.
        Publishes immutable snapshots; call again to present a revision. Without
        configured object storage, files expire with the execution sandbox.
        """
        if not 1 <= len(files) <= 10:
            raise ValueError("Present between 1 and 10 files at a time")
        # Out-of-request, one transaction for the batch: a file that fails
        # leaves no cards for the others, matching the failed tool call. It
        # commits before the tool result is emitted, so cards resolve on arrival.
        async with AsyncSessionLocal() as db:
            service = ArtifactService(db)
            try:
                items = [
                    (
                        await service.publish(
                            thread_id=thread_id,
                            tool_call_id=tool_call_id,
                            file=file,
                            backend=backend,
                            sandbox_source_id=sandbox_source_id,
                        )
                    ).model_dump(mode="json")
                    for file in files
                ]
            except BaseException:
                # The rows roll back with the session; drop their S3 bytes too.
                await service.discard_uploads()
                raise
            # Outside the cleanup: a commit error can follow a successful commit
            # (lost connection), and deleting then would orphan committed rows.
            # The worst case here is an unreferenced object, never a lost file.
            await db.commit()
        summary = [
            {"id": x["id"], "title": x["title"], "temporary": x["temporary"]}
            for x in items
        ]
        # Tool-result content must be a string for every provider adapter.
        return json.dumps({"files": summary}), {"auxilia_artifacts": items}

    return present_files
