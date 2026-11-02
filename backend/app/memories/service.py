import re
import unicodedata
from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError, DomainValidationError, NotFoundError
from app.memories.models import (
    MemoryCategoryDB,
    MemoryDB,
    MemorySource,
)
from app.memories.repository import (
    MemoryCategoryRepository,
    MemoryPreferenceRepository,
    MemoryRepository,
)
from app.memories.schemas import (
    MemoryCategoryCreate,
    MemoryCategoryCreateDB,
    MemoryCategoryGroup,
    MemoryCategoryPatch,
    MemoryCategoryResponse,
    MemoryCreate,
    MemoryCreateDB,
    MemoryLibraryResponse,
    MemoryPatch,
    MemoryPreferencesResponse,
    MemoryResponse,
)


def normalize_category_name(value: str) -> tuple[str, str]:
    name = " ".join(value.split())
    if not name:
        raise DomainValidationError("Memory category name cannot be empty")
    normalized_name = name.casefold()
    if len(name) > 100 or len(normalized_name) > 100:
        raise DomainValidationError("Memory category name cannot exceed 100 characters")
    return name, normalized_name


def normalize_memory_key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9/_-]+", "_", folded.casefold()).strip("_-/")
    key = re.sub(r"_+", "_", key)
    if not key:
        raise DomainValidationError("Memory key cannot be empty")
    return key[:100]


_POSSESSIVE_MEMORY_TITLE = re.compile(r"^(.+?)(?:['’]s)\s+.+$", re.IGNORECASE)


def _memory_subject(title: str) -> str | None:
    """Return the stable subject represented by an English memory title."""
    compact = " ".join(title.split())
    if match := _POSSESSIVE_MEMORY_TITLE.fullmatch(compact):
        compact = match.group(1)
    try:
        return normalize_memory_key(compact)
    except DomainValidationError:
        return None


def _clean_memory_text(value: str, *, field: str, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise DomainValidationError(f"Memory {field} cannot be empty")
    if len(cleaned) > limit:
        raise DomainValidationError(
            f"Memory {field} cannot exceed {limit:,} characters"
        )
    return cleaned


_SENSITIVE_VALUE = re.compile(
    r"""(?ix)
    \b(?:password|passwd|mot\s+de\s+passe|api[\s_-]*key|cl[ée]\s+api|
    access[\s_-]*token|refresh[\s_-]*token|auth(?:entication)?[\s_-]*token|
    secret|private[\s_-]*key)\b
    \s*(?:is|est|:|=)\s*\S{8,}
    """
)
_KNOWN_SECRET = re.compile(
    r"""(?ix)
    \b(?:sk-[a-z0-9_-]{20,}|gh[pousr]_[a-z0-9]{20,}|
    xox[baprs]-[a-z0-9-]{20,}|
    eyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,})\b
    """
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.IGNORECASE,
)
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _is_luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _reject_sensitive_memory(title: str, content: str) -> None:
    value = f"{title}\n{content}"
    contains_card = any(
        _is_luhn_valid(match.group()) for match in _PAYMENT_CARD.finditer(value)
    )
    if (
        _SENSITIVE_VALUE.search(value)
        or _KNOWN_SECRET.search(value)
        or _PRIVATE_KEY.search(value)
        or contains_card
    ):
        raise DomainValidationError(
            "Passwords, authentication secrets and payment-card numbers "
            "cannot be stored as personal memories"
        )


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.categories = MemoryCategoryRepository(db)
        self.memories = MemoryRepository(db)
        self.preferences = MemoryPreferenceRepository(db)

    @staticmethod
    def _memory_response(memory: MemoryDB, category_name: str) -> MemoryResponse:
        return MemoryResponse.model_validate(
            memory,
            update={"category_name": category_name},
        )

    async def list_library(
        self, user_id: UUID, query: str | None = None
    ) -> MemoryLibraryResponse:
        category_rows = await self.categories.list_with_counts(user_id)
        memory_rows = await self.memories.list_for_user(user_id, query=query)
        memories_by_category: dict[UUID, list[MemoryResponse]] = {}
        for memory, category_name in memory_rows:
            memories_by_category.setdefault(memory.category_id, []).append(
                self._memory_response(memory, category_name)
            )
        groups = [
            MemoryCategoryGroup.model_validate(
                category,
                update={
                    "memory_count": count,
                    "memories": memories_by_category.get(category.id, []),
                },
            )
            for category, count in category_rows
            if not query or category.id in memories_by_category
        ]
        return MemoryLibraryResponse(
            categories=groups,
            total=sum(len(group.memories) for group in groups),
        )

    async def list_categories(self, user_id: UUID) -> list[MemoryCategoryResponse]:
        rows = await self.categories.list_with_counts(user_id)
        return [
            MemoryCategoryResponse.model_validate(
                category, update={"memory_count": count}
            )
            for category, count in rows
        ]

    async def get_category(self, category_id: UUID, user_id: UUID) -> MemoryCategoryDB:
        category = await self.categories.get_for_user(category_id, user_id)
        if category is None:
            raise NotFoundError("Memory category not found")
        return category

    async def _create_category(self, user_id: UUID, name: str) -> MemoryCategoryDB:
        display_name, normalized_name = normalize_category_name(name)
        existing = await self.categories.get_by_normalized_name(
            user_id, normalized_name
        )
        if existing is not None:
            raise AlreadyExistsError("Memory category already exists")
        await self.categories.lock_order(user_id)
        position = await self.categories.next_position(user_id)
        try:
            async with self.db.begin_nested():
                return await self.categories.create(
                    MemoryCategoryCreateDB(
                        user_id=user_id,
                        name=display_name,
                        normalized_name=normalized_name,
                        position=position,
                    )
                )
        except IntegrityError as exc:
            raise AlreadyExistsError("Memory category already exists") from exc

    async def create_category(
        self, user_id: UUID, data: MemoryCategoryCreate
    ) -> MemoryCategoryResponse:
        category = await self._create_category(user_id, data.name)
        return MemoryCategoryResponse.model_validate(category)

    async def get_or_create_category(
        self, user_id: UUID, name: str
    ) -> MemoryCategoryDB:
        display_name, normalized_name = normalize_category_name(name)
        existing = await self.categories.get_by_normalized_name(
            user_id, normalized_name
        )
        if existing is not None:
            return existing
        try:
            return await self._create_category(user_id, display_name)
        except AlreadyExistsError:
            category = await self.categories.get_by_normalized_name(
                user_id, normalized_name
            )
            if category is None:
                raise
            return category

    async def update_category(
        self,
        category_id: UUID,
        user_id: UUID,
        data: MemoryCategoryPatch,
    ) -> MemoryCategoryResponse:
        category = await self.get_category(category_id, user_id)
        if data.name is not None:
            name, normalized_name = normalize_category_name(data.name)
            duplicate = await self.categories.get_by_normalized_name(
                user_id, normalized_name
            )
            if duplicate is not None and duplicate.id != category.id:
                raise AlreadyExistsError("Memory category already exists")
            category.name = name
            category.normalized_name = normalized_name
            self.db.add(category)
            try:
                async with self.db.begin_nested():
                    await self.db.flush()
            except IntegrityError as exc:
                raise AlreadyExistsError("Memory category already exists") from exc
            await self.db.refresh(category)
        return MemoryCategoryResponse.model_validate(category)

    async def reorder_categories(
        self, user_id: UUID, category_ids: list[UUID]
    ) -> list[MemoryCategoryResponse]:
        await self.categories.lock_order(user_id)
        existing = await self.list_categories(user_id)
        expected = {category.id for category in existing}
        if len(category_ids) != len(set(category_ids)) or set(category_ids) != expected:
            raise DomainValidationError(
                "Category order must contain every memory category exactly once"
            )
        await self.categories.set_order(user_id, category_ids)
        return await self.list_categories(user_id)

    async def delete_category(self, category_id: UUID, user_id: UUID) -> None:
        category = await self.get_category(category_id, user_id)
        await self.categories.delete(category)

    async def get_memory(self, memory_id: UUID, user_id: UUID) -> MemoryDB:
        memory = await self.memories.get_for_user(memory_id, user_id)
        if memory is None:
            raise NotFoundError("Memory not found")
        return memory

    async def create_memory(self, user_id: UUID, data: MemoryCreate) -> MemoryResponse:
        category = await self.get_category(data.category_id, user_id)
        title = _clean_memory_text(data.title, field="title", limit=200)
        content = _clean_memory_text(data.content, field="content", limit=10_000)
        _reject_sensitive_memory(title, content)
        key = normalize_memory_key(title)
        try:
            async with self.db.begin_nested():
                memory = await self.memories.create(
                    MemoryCreateDB(
                        user_id=user_id,
                        category_id=category.id,
                        key=key,
                        title=title,
                        content=content,
                    )
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A memory with this title already exists in the category"
            ) from exc
        return self._memory_response(memory, category.name)

    async def update_memory(
        self,
        memory_id: UUID,
        user_id: UUID,
        data: MemoryPatch,
    ) -> MemoryResponse:
        memory = await self.get_memory(memory_id, user_id)
        category = await self.get_category(
            data.category_id or memory.category_id, user_id
        )
        patch = data.model_dump(exclude_unset=True)
        if "title" in patch:
            patch["title"] = _clean_memory_text(
                patch["title"], field="title", limit=200
            )
        if "content" in patch:
            patch["content"] = _clean_memory_text(
                patch["content"], field="content", limit=10_000
            )
        _reject_sensitive_memory(
            patch.get("title", memory.title),
            patch.get("content", memory.content),
        )
        if "category_id" in patch:
            duplicate = await self.memories.get_by_category_key(
                user_id, category.id, memory.key
            )
            if duplicate is not None and duplicate.id != memory.id:
                raise AlreadyExistsError(
                    "A memory with the same key already exists in that category"
                )
        memory.sqlmodel_update(patch)
        memory.source = MemorySource.manual
        memory.source_thread_id = None
        self.db.add(memory)
        try:
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as exc:
            raise AlreadyExistsError(
                "A memory with the same key already exists in that category"
            ) from exc
        await self.db.refresh(memory)
        return self._memory_response(memory, category.name)

    async def delete_memory(self, memory_id: UUID, user_id: UUID) -> None:
        memory = await self.get_memory(memory_id, user_id)
        await self.memories.delete(memory)

    async def get_preferences(self, user_id: UUID) -> MemoryPreferencesResponse:
        preference = await self.preferences.get_for_user(user_id)
        return MemoryPreferencesResponse(
            auto_capture_enabled=(
                preference.auto_capture_enabled if preference is not None else False
            )
        )

    async def enable_auto_capture_for_new_user(self, user_id: UUID) -> None:
        await self.preferences.set_auto_capture(user_id, True)

    async def set_auto_capture(
        self, user_id: UUID, enabled: bool
    ) -> MemoryPreferencesResponse:
        preference = await self.preferences.set_auto_capture(user_id, enabled)
        return MemoryPreferencesResponse(
            auto_capture_enabled=preference.auto_capture_enabled
        )

    async def upsert_from_assistant(
        self,
        *,
        user_id: UUID,
        thread_id: str,
        category_name: str,
        key: str,
        title: str,
        content: str,
    ) -> MemoryDB:
        category = await self.get_or_create_category(user_id, category_name)
        memory_key = normalize_memory_key(key)
        clean_title = _clean_memory_text(title, field="title", limit=200)
        clean_content = _clean_memory_text(content, field="content", limit=10_000)
        _reject_sensitive_memory(clean_title, clean_content)
        if (
            await self.memories.get_by_category_key(user_id, category.id, memory_key)
            is None
        ):
            subject = _memory_subject(clean_title)
            same_subject = (
                [
                    memory
                    for memory, _ in await self.memories.list_for_user(
                        user_id,
                        category_id=category.id,
                    )
                    if _memory_subject(memory.title) == subject
                ]
                if subject is not None
                else []
            )
            if len(same_subject) == 1:
                memory_key = same_subject[0].key
        return await self.memories.upsert_assistant(
            user_id=user_id,
            category_id=category.id,
            key=memory_key,
            title=clean_title,
            content=clean_content,
            source_thread_id=thread_id,
        )

    async def delete_from_assistant(
        self,
        *,
        user_id: UUID,
        category_name: str,
        key: str,
    ) -> UUID:
        _, normalized_name = normalize_category_name(category_name)
        category = await self.categories.get_by_normalized_name(
            user_id, normalized_name
        )
        if category is None:
            raise NotFoundError("Memory category not found")
        memory = await self.memories.get_by_category_key(
            user_id,
            category.id,
            normalize_memory_key(key),
        )
        if memory is None:
            raise NotFoundError("Memory not found")
        memory_id = memory.id
        await self.memories.delete(memory)
        return memory_id

    async def delete_category_from_assistant(
        self,
        *,
        user_id: UUID,
        category_name: str,
    ) -> list[UUID]:
        _, normalized_name = normalize_category_name(category_name)
        category = await self.categories.get_by_normalized_name(
            user_id, normalized_name
        )
        if category is None:
            raise NotFoundError("Memory category not found")
        rows = await self.memories.list_for_user(
            user_id,
            category_id=category.id,
        )
        memory_ids = [memory.id for memory, _ in rows]
        await self.categories.delete(category)
        return memory_ids


def get_memory_service(
    # Category creation is commonly followed immediately by memory creation.
    # Finalize this module's request transaction before sending the response,
    # so the dependent request cannot race get_db's post-yield commit.
    db: AsyncSession = Depends(get_db, scope="function"),
) -> MemoryService:
    return MemoryService(db)
