from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel


ItemType = TypeVar("ItemType")


class PageParams:
    """Query-string pagination parameters (``?limit=&offset=``).

    Bound as a class dependency on list endpoints: ``page: PageParams = Depends()``.
    """

    def __init__(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        self.limit = limit
        self.offset = offset


class Page(BaseModel, Generic[ItemType]):
    """Envelope returned by every paginated list endpoint."""

    items: list[ItemType]
    total: int
    limit: int
    offset: int

    @classmethod
    def build(
        cls, items: list[ItemType], total: int, page: PageParams
    ) -> "Page[ItemType]":
        return cls(items=items, total=total, limit=page.limit, offset=page.offset)
