from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.exceptions import NotFoundError
from app.repository import BaseRepository


# Matches BaseRepository's bound — see the comment there for why it is SQLModel
# and not BaseDBModel.
ModelType = TypeVar("ModelType", bound=SQLModel)
RepositoryType = TypeVar("RepositoryType", bound=BaseRepository)


class BaseService(Generic[ModelType, RepositoryType]):
    """Common CRUD boilerplate for services backed by a BaseRepository.

    Subclasses set ``not_found_message`` and construct the concrete repository
    in ``__init__``. The request-scoped ``get_db`` dependency commits once at
    the end of the request, so service methods only ``flush`` when they need
    to read back a server-generated value.
    """

    not_found_message: str = "Not found"

    def __init__(self, db: AsyncSession, repository: RepositoryType):
        self.db = db
        self.repository = repository

    async def get_or_404(self, entity_id: UUID | str) -> ModelType:
        # `UUID | str` is load-bearing, not laziness: `ThreadService` is a
        # `BaseService[ThreadDB, ...]` and `ThreadDB.id` is a string, so narrowing
        # this to UUID breaks the thread path. (Named `entity_id` rather than `id`
        # only to stop shadowing the builtin in the most-called helper here.)
        obj = await self.repository.get(entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_message)
        return obj
