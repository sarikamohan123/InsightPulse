import uuid

from sqlalchemy import exists, select

from app.models.review import Review
from app.models.review_source import ReviewSource, SourceType
from app.repositories.base import BaseRepository


class ReviewSourceRepository(BaseRepository[ReviewSource]):
    model = ReviewSource

    async def create(
        self,
        organization_id: uuid.UUID,
        name: str,
        source_type: SourceType,
        config: dict | None,
    ) -> ReviewSource:
        source = ReviewSource(
            organization_id=organization_id,
            name=name,
            source_type=source_type,
            config=config or {},
        )
        self.session.add(source)
        await self.session.flush()
        await self.session.refresh(source)
        return source

    async def list_all(  # type: ignore[override]
        self,
        organization_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> list[ReviewSource]:
        """Return sources for this org. Active-only by default."""
        stmt = select(ReviewSource).where(
            ReviewSource.organization_id == organization_id
        )
        if not include_inactive:
            stmt = stmt.where(ReviewSource.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        source: ReviewSource,
        name: str | None = None,
        config: dict | None = None,
    ) -> ReviewSource:
        """Apply partial updates to a source and return the refreshed object."""
        if name is not None:
            source.name = name
        if config is not None:
            source.config = config
        await self.session.flush()
        await self.session.refresh(source)
        return source

    async def soft_delete(self, source: ReviewSource) -> None:
        """Deactivate a source without removing it. Used when it has reviews."""
        source.is_active = False
        await self.session.flush()

    async def hard_delete(self, source: ReviewSource) -> None:
        """Permanently remove a source. Only safe when it has no reviews."""
        await self.session.delete(source)
        await self.session.flush()

    async def has_reviews(self, source_id: uuid.UUID) -> bool:
        """Return True if this source has at least one review. Cheap EXISTS query."""
        result = await self.session.execute(
            select(exists().where(Review.source_id == source_id))
        )
        return result.scalar()  # type: ignore[return-value]
