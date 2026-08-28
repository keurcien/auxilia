from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models import BaseDBModel
from app.repository import BaseRepository


# Same bound as BaseRepository's, so `self.repository.get(...)` type-checks and a
# service can't be parameterised over a model its repository can't address.
ModelType = TypeVar("ModelType", bound=BaseDBModel)
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

    async def get_or_404(self, entity_id: UUID) -> ModelType:
        # Not `id` — shadowing the builtin in the most-called helper in the
        # codebase is the kind of thing that reads fine until someone needs `id()`.
        obj = await self.repository.get(entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_message)
        return obj
