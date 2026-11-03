from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.models import ToolStatus
from app.agents.run_spec import RunSpec
from app.artifacts.files import decode_text, is_text_mime
from app.artifacts.service import ArtifactService, attachment_mime
from app.artifacts.settings import artifact_settings
from app.database import get_checkpointer, get_db
from app.exceptions import DomainValidationError, NotFoundError
from app.model_providers.service import ModelService
from app.pagination import Page, PageParams
from app.projects.service import ProjectService
from app.realtime.schemas import WorkspaceEventKind
from app.realtime.service import stage_workspace_event
from app.runtime.runs.repository import RunRepository
from app.runtime.runs.service import RunService
from app.service import BaseService
from app.skills.repository import SkillRepository
from app.threads.models import ThreadDB, ThreadSource, ThreadToolMode
from app.threads.repository import ThreadRepository
from app.threads.schemas import (
    AgentThreadResponse,
    ThreadBulkPlacementResponse,
    ThreadBulkPlacementUpdate,
    ThreadCompletionUpdate,
    ThreadCreate,
    ThreadMemoriesUpdate,
    ThreadModelUpdate,
    ThreadPatch,
    ThreadPlacementFilter,
    ThreadPlacementResult,
    ThreadPlacementUpdate,
    ThreadResourcesPatch,
    ThreadResponse,
    ThreadStartCreate,
)
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


def _thread_with_agent(
    thread: ThreadDB,
    agent_name: str | None,
    agent_emoji: str | None,
    agent_color: str | None,
    agent_image_revision: UUID | None,
    agent_archived: bool,
) -> ThreadResponse:
    return ThreadResponse.model_validate(
        thread,
        update={
            "agent_name": agent_name,
            "agent_emoji": agent_emoji,
            "agent_color": agent_color,
            "agent_image_revision": agent_image_revision,
            "agent_archived": agent_archived,
        },
    )


def _agent_thread(
    thread: ThreadDB,
    agent_name: str | None,
    agent_emoji: str | None,
    agent_color: str | None,
    agent_image_revision: UUID | None,
    agent_archived: bool,
    user_email: str | None,
    user_name: str | None,
) -> AgentThreadResponse:
    return AgentThreadResponse.model_validate(
        thread,
        update={
            "agent_name": agent_name,
            "agent_emoji": agent_emoji,
            "agent_color": agent_color,
            "agent_image_revision": agent_image_revision,
            "agent_archived": agent_archived,
            "user_email": user_email,
            "user_name": user_name,
        },
    )


class ThreadService(BaseService[ThreadDB, ThreadRepository]):
    not_found_message = "Thread not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(db, ThreadRepository(db, workspace_id))
        self.workspace_id = workspace_id

    async def get(self, thread_id: str) -> ThreadDB:
        return await self.get_or_404(thread_id)

    async def _resolve_agent_defaults(
        self,
        model_id: str | None,
        reasoning_effort: str | None,
    ) -> tuple[str | None, str | None]:
        model_service = ModelService(self.db, self.workspace_id)
        if model_id is not None and await model_service.is_available(model_id):
            if reasoning_effort is not None and not (
                await ModelService.is_reasoning_effort_declared(
                    model_id, reasoning_effort
                )
            ):
                reasoning_effort = None
            return model_id, reasoning_effort
        return await model_service.get_default_model_id(), None

    async def get_with_agent(self, thread_id: str) -> ThreadResponse:
        row = await self.repository.get_with_agent(thread_id)
        if not row:
            raise NotFoundError(self.not_found_message)
        response = _thread_with_agent(*row)
        response.model_available = await ModelService(
            self.db, self.workspace_id
        ).is_available(response.model_id)
        return response

    async def list(
        self,
        user_id: UUID,
        page: PageParams,
        query: str | None = None,
        *,
        project_id: UUID | None = None,
        folder_id: UUID | None = None,
        placement: ThreadPlacementFilter = "all",
        include_api: bool = False,
    ) -> Page[ThreadResponse]:
        if placement == "unassigned" and (
            project_id is not None or folder_id is not None
        ):
            raise DomainValidationError(
                "Unassigned conversations cannot be filtered by project or folder"
            )
        rows, total = await self.repository.list_for_user(
            user_id,
            page,
            query=query,
            project_id=project_id,
            folder_id=folder_id,
            placement=placement,
            include_api=include_api,
        )
        return Page.build([_thread_with_agent(*row) for row in rows], total, page)

    async def list_for_agent(
        self, agent_id: UUID, page: PageParams
    ) -> Page[AgentThreadResponse]:
        rows, total = await self.repository.list_for_agent(agent_id, page)
        return Page.build([_agent_thread(*row) for row in rows], total, page)

    async def list_for_trigger(
        self, trigger_id: UUID, since: datetime | None = None
    ) -> list[ThreadDB]:
        return await self.repository.list_for_trigger(trigger_id, since=since)

    async def _default_disabled_resource_ids(
        self, spec: RunSpec
    ) -> tuple[list[UUID], list[UUID], list[UUID], list[UUID]]:
        return (
            [
                binding.mcp_server_id
                for binding in spec.all_mcp_bindings
                if not binding.enabled_by_default
            ],
            list(
                await SkillRepository(
                    self.db, self.workspace_id
                ).list_disabled_by_default_ids_for_agents(spec.all_agent_ids)
            ),
            list(
                {
                    agent_spec.sandbox.row.id
                    for agent_spec in [spec.agent, *spec.subagents]
                    if agent_spec.sandbox is not None
                    and not agent_spec.sandbox.enabled_by_default
                }
            ),
            [
                subagent.id
                for subagent in spec.subagents
                if not subagent.enabled_by_default
            ],
        )

    async def create(
        self,
        data: ThreadCreate,
        user_id: UUID,
        source: ThreadSource,
        trigger_id: UUID | None = None,
        placement_user: UserDB | None = None,
    ) -> ThreadResponse:
        if placement_user is not None:
            await ProjectService(self.db, self.workspace_id).validate_placement(
                data.project_id,
                data.folder_id,
                placement_user,
                lock_project=data.project_id is not None,
            )
        elif data.folder_id is not None and data.project_id is None:
            raise DomainValidationError("A folder requires a project")
        spec = await AgentRepository(self.db, self.workspace_id).get_run_spec(
            data.agent_id
        )
        if spec is None:
            raise NotFoundError("Agent not found")
        model_id = data.model_id
        reasoning_effort = data.reasoning_effort
        if model_id is None:
            model_id, default_effort = await self._resolve_agent_defaults(
                spec.agent.default_model_id,
                spec.agent.default_reasoning_effort,
            )
            if reasoning_effort is None:
                reasoning_effort = default_effort
        elif (
            model_id == spec.agent.default_model_id
            and reasoning_effort is None
            and "reasoning_effort" not in data.model_fields_set
        ):
            default_effort = spec.agent.default_reasoning_effort
            if default_effort is None or (
                await ModelService.is_reasoning_effort_declared(
                    model_id, default_effort
                )
            ):
                reasoning_effort = default_effort
        (
            default_disabled_mcp_server_ids,
            default_disabled_skill_ids,
            default_disabled_sandbox_ids,
            default_disabled_subagent_ids,
        ) = await self._default_disabled_resource_ids(spec)
        (
            disabled_mcp_server_ids,
            disabled_skill_ids,
            disabled_sandbox_ids,
            disabled_subagent_ids,
        ) = await self.normalize_resource_ids(
            spec,
            (
                data.disabled_mcp_server_ids
                if "disabled_mcp_server_ids" in data.model_fields_set
                else default_disabled_mcp_server_ids
            ),
            (
                data.disabled_skill_ids
                if "disabled_skill_ids" in data.model_fields_set
                else default_disabled_skill_ids
            ),
            (
                data.disabled_sandbox_ids
                if "disabled_sandbox_ids" in data.model_fields_set
                else default_disabled_sandbox_ids
            ),
            (
                data.disabled_subagent_ids
                if "disabled_subagent_ids" in data.model_fields_set
                else default_disabled_subagent_ids
            ),
            project_id=data.project_id,
            tolerated_mcp_ids=(
                set(data.disabled_mcp_server_ids)
                if source == ThreadSource.trigger
                and "disabled_mcp_server_ids" in data.model_fields_set
                else None
            ),
            tolerated_skill_ids=(
                set(data.disabled_skill_ids)
                if source == ThreadSource.trigger
                and "disabled_skill_ids" in data.model_fields_set
                else None
            ),
            tolerated_sandbox_ids=(
                set(data.disabled_sandbox_ids)
                if source == ThreadSource.trigger
                and "disabled_sandbox_ids" in data.model_fields_set
                else None
            ),
            tolerated_subagent_ids=(
                set(data.disabled_subagent_ids)
                if source == ThreadSource.trigger
                and "disabled_subagent_ids" in data.model_fields_set
                else None
            ),
        )
        # Strict at selection time (unlike model availability, which is only
        # flagged): an undeclared effort level is a client bug, and letting it
        # persist would silently degrade to the model default on every run.
        # Trigger firings are exempt — their effort was validated when the
        # trigger was saved, and a later catalog edit must skip nothing worse
        # than the effort (ensure_available clamps it at run time), not the
        # whole scheduled firing.
        if reasoning_effort is not None and source != ThreadSource.trigger:
            await ModelService.validate_reasoning_effort(model_id, reasoning_effort)
        if "disabled_mcp_tools" in data.model_fields_set:
            disabled_mcp_tools = {
                str(server_id): list(dict.fromkeys(tool_names))
                for server_id, tool_names in data.disabled_mcp_tools.items()
            }
        elif source == ThreadSource.trigger:
            disabled_mcp_tools: dict[str, list[str]] = {}
            for binding in spec.all_mcp_bindings:
                rejected = disabled_mcp_tools.setdefault(str(binding.mcp_server_id), [])
                rejected.extend(
                    name
                    for name, status in (binding.tools or {}).items()
                    if status == ToolStatus.needs_approval and name not in rejected
                )
        else:
            disabled_mcp_tools = {}
        # `trigger_id` is a keyword (not a ThreadCreate field) so API clients
        # can't attach arbitrary threads to a trigger — only the scanner sets it.
        thread = ThreadDB(
            **data.model_dump(
                exclude_none=True,
                exclude={
                    "model_id",
                    "reasoning_effort",
                    "disabled_mcp_server_ids",
                    "disabled_skill_ids",
                    "disabled_sandbox_ids",
                    "disabled_subagent_ids",
                    "disabled_mcp_tools",
                },
            ),
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            workspace_id=self.workspace_id,
            user_id=user_id,
            source=source,
            trigger_id=trigger_id,
            disabled_mcp_server_ids=disabled_mcp_server_ids,
            disabled_skill_ids=disabled_skill_ids,
            disabled_sandbox_ids=disabled_sandbox_ids,
            disabled_subagent_ids=disabled_subagent_ids,
            disabled_mcp_tools=disabled_mcp_tools,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.threads,
            target_user_id=user_id,
            thread_id=thread.id,
        )
        if source == ThreadSource.trigger:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.trigger_history,
            )
        if thread.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        # Compute (not default) the availability flag: creating a thread on a
        # disabled model is possible via the API, and the schema default
        # (True) must not masquerade as a runnable thread.
        return ThreadResponse.model_validate(
            thread,
            update={
                "model_available": await ModelService(
                    self.db, self.workspace_id
                ).is_available(thread.model_id)
            },
        )

    async def create_with_initial_run(
        self,
        data: ThreadStartCreate,
        files: list[UploadFile],
        user_id: UUID,
        source: ThreadSource,
        placement_user: UserDB | None = None,
    ) -> ThreadResponse:
        """Persist the thread, its attachments and first run atomically."""
        text = data.message_text if data.message_text.strip() else ""
        if not text and not files:
            raise DomainValidationError("The first message cannot be empty")
        if len(files) > 10:
            raise DomainValidationError("A message can contain at most 10 files")

        placement = {}
        if "project_id" in data.model_fields_set:
            placement["project_id"] = data.project_id
        if "folder_id" in data.model_fields_set:
            placement["folder_id"] = data.folder_id
        thread_data = data.thread.model_copy(
            update={"first_message_content": text or None, **placement}
        )
        artifacts = ArtifactService(self.db, self.workspace_id)
        try:
            thread = await self.create(
                thread_data,
                user_id,
                source,
                placement_user=placement_user,
            )
            attachment_metadata: list[dict[str, str]] = []
            image_parts: list[dict] = []
            inline_text_parts: list[dict] = []
            inline_text_files: list[dict[str, str]] = []
            inline_text_chars = 0
            for upload in files:
                raw = await upload.read(artifact_settings.max_bytes + 1)
                if len(raw) > artifact_settings.max_bytes:
                    raise DomainValidationError("Attachment exceeds the size limit")
                filename = upload.filename or "file"
                inline_filename = filename
                mime_type = await asyncio.to_thread(attachment_mime, filename, raw)
                decoded = await asyncio.to_thread(
                    decode_text,
                    raw,
                    allow_legacy=is_text_mime(mime_type),
                )
                is_text = decoded is not None
                if is_text and not is_text_mime(mime_type):
                    mime_type = "text/plain"
                if not is_text and artifact_settings.provider and data.store_files:
                    item = await artifacts.attach(thread.id, filename, raw)
                    mime_type = item.mime_type
                    inline_filename = item.filename
                    attachment_metadata.append(
                        {
                            "id": str(item.id),
                            "filename": item.filename,
                            "media_type": mime_type,
                        }
                    )
                elif not is_text and not (
                    data.include_images and mime_type.startswith("image/")
                ):
                    raise DomainValidationError(
                        "Binary attachments need a configured object store"
                    )
                if is_text:
                    if decoded is None:  # narrowed above; keeps mypy explicit
                        raise DomainValidationError(
                            f"{filename} is not a valid text file"
                        )
                    inline_text_chars += len(decoded)
                    if inline_text_chars > 100_000:
                        raise DomainValidationError(
                            "Text attachments can contain at most 100,000 characters per message"
                        )
                    inline_text_parts.append(
                        {
                            "type": "text",
                            "text": (
                                f'Attached text file "{inline_filename}":\n\n{decoded}'
                            ),
                        }
                    )
                    inline_text_files.append(
                        {"filename": inline_filename, "media_type": mime_type}
                    )
                if data.include_images and mime_type.startswith("image/"):
                    encoded = base64.b64encode(raw).decode("ascii")
                    image_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                                "detail": "auto",
                            },
                        }
                    )

            content: str | list[dict]
            if image_parts or inline_text_parts:
                content = (
                    ([{"type": "text", "text": text}] if text else [])
                    + image_parts
                    + inline_text_parts
                )
            else:
                content = text
            message: dict = {"type": "human", "content": content}
            additional_kwargs = {
                **({"attachments": attachment_metadata} if attachment_metadata else {}),
                **({"display_text": text} if inline_text_parts else {}),
                **(
                    {
                        "inline_text_files": [
                            {
                                "block_index": (
                                    (1 if text else 0) + len(image_parts) + index
                                ),
                                **inline_file,
                            }
                            for index, inline_file in enumerate(inline_text_files)
                        ]
                    }
                    if inline_text_parts
                    else {}
                ),
            }
            if additional_kwargs:
                message["additional_kwargs"] = additional_kwargs
            await RunService().create_in_session(
                self.db,
                thread_id=thread.id,
                user_id=str(user_id),
                input={"messages": [message]},
                multitask_strategy="enqueue",
                text_only_when_queued=True,
            )
            return thread
        except BaseException:
            await artifacts.discard_uploads()
            raise

    async def update(self, thread_id: str, data: ThreadPatch) -> ThreadResponse:
        thread = await self._lock_editable(thread_id)
        await self.repository.update(thread, data)
        if thread.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return await self.get_with_agent(thread_id)

    async def update_model(
        self, thread_id: str, data: ThreadModelUpdate
    ) -> ThreadResponse:
        await self._lock_editable(thread_id)
        await ModelService(self.db, self.workspace_id).ensure_available(data.model_id)
        await ModelService.validate_reasoning_effort(
            data.model_id, data.reasoning_effort
        )
        await self.repository.set_model(thread_id, data.model_id, data.reasoning_effort)
        return await self.get_with_agent(thread_id)

    async def update_memories(
        self, thread_id: str, data: ThreadMemoriesUpdate
    ) -> ThreadResponse:
        await self._lock_editable(thread_id)
        await self.repository.set_memories_enabled(thread_id, data.memories_enabled)
        return await self.get_with_agent(thread_id)

    async def update_resources(
        self, thread_id: str, data: ThreadResourcesPatch
    ) -> ThreadResponse:
        thread = await self._lock_editable(thread_id)
        spec = await AgentRepository(self.db, self.workspace_id).get_run_spec(
            thread.agent_id
        )
        if spec is None:
            raise NotFoundError("Agent not found")
        (
            disabled_mcp_server_ids,
            disabled_skill_ids,
            disabled_sandbox_ids,
            disabled_subagent_ids,
        ) = await self.normalize_resource_ids(
            spec,
            data.disabled_mcp_server_ids,
            data.disabled_skill_ids,
            data.disabled_sandbox_ids,
            data.disabled_subagent_ids,
            project_id=thread.project_id,
            tolerated_mcp_ids={
                UUID(resource_id) for resource_id in thread.disabled_mcp_server_ids
            },
            tolerated_skill_ids={
                UUID(resource_id) for resource_id in thread.disabled_skill_ids
            },
            tolerated_sandbox_ids={
                UUID(resource_id) for resource_id in thread.disabled_sandbox_ids
            },
            tolerated_subagent_ids={
                UUID(resource_id) for resource_id in thread.disabled_subagent_ids
            },
        )
        await self.repository.set_resources(
            thread_id,
            disabled_mcp_server_ids,
            disabled_skill_ids,
            disabled_sandbox_ids,
            disabled_subagent_ids,
            data.tool_mode,
        )
        return await self.get_with_agent(thread_id)

    @staticmethod
    def _ensure_not_completed(thread: ThreadDB) -> None:
        if thread.completed_at is not None:
            raise DomainValidationError("Completed threads are read-only")

    async def _lock_editable(self, thread_id: str) -> ThreadDB:
        thread = await self.repository.lock(thread_id)
        if thread is None:
            raise NotFoundError(self.not_found_message)
        self._ensure_not_completed(thread)
        return thread

    async def update_placement(
        self,
        thread_id: str,
        data: ThreadPlacementUpdate,
        user: UserDB,
    ) -> ThreadResponse:
        await ProjectService(self.db, self.workspace_id).validate_placement(
            data.project_id,
            data.folder_id,
            user,
            lock_project=data.project_id is not None,
        )
        thread = await self.repository.lock_owned(thread_id, user.id)
        if thread is None:
            raise NotFoundError(self.not_found_message)
        previous_project_id = thread.project_id
        await self.repository.set_placement(thread_id, data.project_id, data.folder_id)
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.threads,
            target_user_id=thread.user_id,
            thread_id=thread.id,
        )
        if previous_project_id is not None or data.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return await self.get_with_agent(thread_id)

    async def update_placements(
        self,
        data: ThreadBulkPlacementUpdate,
        user: UserDB,
    ) -> ThreadBulkPlacementResponse:
        thread_ids = list(dict.fromkeys(data.thread_ids))
        await ProjectService(self.db, self.workspace_id).validate_placement(
            data.project_id,
            data.folder_id,
            user,
            lock_project=data.project_id is not None,
        )
        threads = await self.repository.lock_owned_many(thread_ids, user.id)
        if len(threads) != len(thread_ids):
            raise NotFoundError(self.not_found_message)

        by_id = {thread.id: thread for thread in threads}
        items = [
            ThreadPlacementResult(
                thread_id=thread_id,
                previous_project_id=by_id[thread_id].project_id,
                previous_folder_id=by_id[thread_id].folder_id,
                project_id=data.project_id,
                folder_id=data.folder_id,
            )
            for thread_id in thread_ids
        ]
        await self.repository.set_placement_many(
            thread_ids,
            user.id,
            data.project_id,
            data.folder_id,
        )
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.threads,
            target_user_id=user.id,
        )
        if data.project_id is not None or any(
            item.previous_project_id is not None for item in items
        ):
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return ThreadBulkPlacementResponse(items=items)

    async def update_completion(
        self,
        thread_id: str,
        data: ThreadCompletionUpdate,
    ) -> ThreadResponse:
        thread = await self.repository.lock(thread_id)
        if thread is None:
            raise NotFoundError(self.not_found_message)
        if data.completed and thread.completed_at is None:
            active = await RunRepository(
                self.db, self.workspace_id
            ).get_active_for_thread(thread_id)
            queued = await RunRepository(
                self.db, self.workspace_id
            ).list_queued_prompts(thread_id)
            if active is not None or queued or thread.awaiting_input:
                raise DomainValidationError(
                    "A thread with active or queued work cannot be completed"
                )
        await self.repository.set_completed_at(
            thread_id, datetime.now(UTC) if data.completed else None
        )
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.threads,
            target_user_id=thread.user_id,
            thread_id=thread.id,
        )
        if thread.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        return await self.get_with_agent(thread_id)

    async def normalize_resource_ids(
        self,
        spec: RunSpec,
        disabled_mcp_server_ids: list[UUID],
        disabled_skill_ids: list[UUID],
        disabled_sandbox_ids: list[UUID],
        disabled_subagent_ids: list[UUID],
        *,
        project_id: UUID | None = None,
        tolerated_mcp_ids: set[UUID] | None = None,
        tolerated_skill_ids: set[UUID] | None = None,
        tolerated_sandbox_ids: set[UUID] | None = None,
        tolerated_subagent_ids: set[UUID] | None = None,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        mcp_ids = list(dict.fromkeys(disabled_mcp_server_ids))
        skill_ids = list(dict.fromkeys(disabled_skill_ids))
        sandbox_ids = list(dict.fromkeys(disabled_sandbox_ids))
        subagent_ids = list(dict.fromkeys(disabled_subagent_ids))
        available_mcp_ids = {binding.mcp_server_id for binding in spec.all_mcp_bindings}
        available_skill_ids = await SkillRepository(
            self.db, self.workspace_id
        ).list_attached_ids_for_agents(spec.all_agent_ids)
        if project_id is not None:
            available_skill_ids.update(
                await ProjectService(
                    self.db, self.workspace_id
                ).repository.list_skill_ids(project_id)
            )
        available_sandbox_ids = {sandbox.id for sandbox in spec.all_sandbox_rows}
        available_subagent_ids = {subagent.id for subagent in spec.subagents}
        unknown_mcp_ids = (
            set(mcp_ids) - available_mcp_ids - (tolerated_mcp_ids or set())
        )
        unknown_skill_ids = (
            set(skill_ids) - available_skill_ids - (tolerated_skill_ids or set())
        )
        unknown_sandbox_ids = (
            set(sandbox_ids) - available_sandbox_ids - (tolerated_sandbox_ids or set())
        )
        unknown_subagent_ids = (
            set(subagent_ids)
            - available_subagent_ids
            - (tolerated_subagent_ids or set())
        )
        if (
            unknown_mcp_ids
            or unknown_skill_ids
            or unknown_sandbox_ids
            or unknown_subagent_ids
        ):
            raise DomainValidationError(
                "Thread resources must belong to the agent or one of its subagents."
            )
        return (
            [str(resource_id) for resource_id in mcp_ids],
            [str(resource_id) for resource_id in skill_ids],
            [str(resource_id) for resource_id in sandbox_ids],
            [str(resource_id) for resource_id in subagent_ids],
        )

    async def delete(self, thread_id: str) -> ThreadDB:
        thread = await self.get_or_404(thread_id)
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.threads,
            target_user_id=thread.user_id,
            thread_id=thread.id,
        )
        if thread.trigger_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.trigger_history,
            )
        if thread.project_id is not None:
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.projects,
            )
        await self.db.delete(thread)
        return thread

    async def list_ids(self) -> list[str]:
        return await self.repository.list_ids()

    async def delete_rows_for_agent(self, agent_id: UUID) -> list[str]:
        """Bulk-delete an agent's thread rows (one statement) and return their
        ids so the caller can purge LangGraph checkpoints afterwards.

        Checkpoint deletion is intentionally NOT done here: it is an external,
        non-transactional side effect and must run only after all DB deletes
        have succeeded — see ``purge_checkpoints``."""
        thread_ids = await self.repository.list_ids_for_agent(agent_id)
        if thread_ids:
            await self.repository.delete_for_agent(agent_id)
            await self.db.flush()
        return thread_ids

    async def purge_checkpoints(self, thread_ids: list[str]) -> None:
        """Delete the LangGraph checkpoints for the given threads.

        This writes to a separate, auto-committed connection (the checkpointer),
        so it cannot be rolled back with the request transaction. Callers must
        run it last — once every DB delete has succeeded — to avoid leaving
        threads in Postgres without their checkpoints."""
        if not thread_ids:
            return
        async with get_checkpointer() as checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(
                    thread_id=f"{self.workspace_id}:{thread_id}"
                )

    async def clear_sandbox(self, sandbox_id: UUID) -> None:
        """Forget the sandbox of every thread this sandbox row stamped — run
        by the sandbox delete endpoint before the row goes (see the
        repository method for why a stale id must not survive)."""
        await self.repository.clear_sandbox(sandbox_id)

    async def get_or_create(
        self,
        ts: str,
        agent_id: str,
        question: str | None,
        user_id: str,
        source: ThreadSource = ThreadSource.slack,
        tool_mode: ThreadToolMode | None = None,
    ) -> ThreadDB:
        """Return the existing thread or create a side-channel thread.

        The side-channel caller owns the session lifecycle and final commit.
        """
        thread = await self.repository.get(ts)
        if thread is None:
            spec = await AgentRepository(self.db, self.workspace_id).get_run_spec(
                UUID(agent_id)
            )
            if spec is None:
                raise NotFoundError("Agent not found")
            # Side channels have no model picker, so new threads use the
            # workspace default unless the agent defines an available override.
            model_id, reasoning_effort = await self._resolve_agent_defaults(
                spec.agent.default_model_id,
                spec.agent.default_reasoning_effort,
            )
            (
                default_disabled_mcp_server_ids,
                default_disabled_skill_ids,
                default_disabled_sandbox_ids,
                default_disabled_subagent_ids,
            ) = await self._default_disabled_resource_ids(spec)
            (
                disabled_mcp_server_ids,
                disabled_skill_ids,
                disabled_sandbox_ids,
                disabled_subagent_ids,
            ) = await self.normalize_resource_ids(
                spec,
                default_disabled_mcp_server_ids,
                default_disabled_skill_ids,
                default_disabled_sandbox_ids,
                default_disabled_subagent_ids,
            )
            thread = ThreadDB(
                id=ts,
                workspace_id=self.workspace_id,
                agent_id=agent_id,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                first_message_content=question,
                user_id=user_id,
                source=source,
                tool_mode=tool_mode,
                disabled_mcp_server_ids=disabled_mcp_server_ids,
                disabled_skill_ids=disabled_skill_ids,
                disabled_sandbox_ids=disabled_sandbox_ids,
                disabled_subagent_ids=disabled_subagent_ids,
            )
            self.db.add(thread)
            await self.db.flush()
            await self.db.refresh(thread)
            await stage_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                kind=WorkspaceEventKind.threads,
                target_user_id=UUID(user_id),
                thread_id=thread.id,
            )
        return thread


def get_thread_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> ThreadService:
    return ThreadService(db, workspace_id)


def get_thread_service_before_response(
    # A memory toggle is immediately actionable by the next queued run. Close
    # its transaction before responding so the worker cannot read the old flag.
    db: AsyncSession = Depends(get_db, scope="function"),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> ThreadService:
    return ThreadService(db, workspace_id)
