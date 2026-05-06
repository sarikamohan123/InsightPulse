from typing import ClassVar, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Typed base for all repositories.

    Subclasses must set the `model` class variable to their SQLAlchemy model.
    Subclasses receive the session via constructor — never via global state.

    `get_by_id` and `list_all` are org-scoped by default — both require
    `organization_id` and are never optional. These cover the standard
    tenant-owned read patterns. Repos that need custom query shapes define
    additional methods and always pass `organization_id` as a required parameter.
    """

    model: ClassVar[type]  # subclasses must set: model = MyModel

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID, organization_id: UUID) -> T | None:
        """Return the record with the given id scoped to the given org, or None."""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.id == id)
            .where(self.model.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, organization_id: UUID) -> list[T]:
        """Return all records belonging to the given org."""
        result = await self.session.execute(
            select(self.model).where(self.model.organization_id == organization_id)
        )
        return list(result.scalars().all())
