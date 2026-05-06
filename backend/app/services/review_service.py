import uuid
from datetime import date

from app.core.exceptions import ConflictError, NotFoundError
from app.models.review import Review
from app.models.review_source import ReviewSource
from app.providers.sources.base import SourceProvider
from app.repositories.review_repo import ReviewRepository
from app.repositories.review_source_repo import ReviewSourceRepository
from app.schemas.source import IngestResponse, SourceCreate, SourceUpdate


class ReviewService:
    """
    All business logic for sources and reviews.

    Constructor receives its dependencies as abstract types (SourceProvider)
    or typed repos — never as concrete HTTP or DB objects. This makes the
    service independently testable with mocks.
    """

    def __init__(
        self,
        source_repo: ReviewSourceRepository,
        review_repo: ReviewRepository,
        source_provider: SourceProvider,
    ) -> None:
        self._source_repo = source_repo
        self._review_repo = review_repo
        self._source_provider = source_provider

    # ------------------------------------------------------------------
    # Source CRUD
    # ------------------------------------------------------------------

    async def create_source(
        self, organization_id: uuid.UUID, data: SourceCreate
    ) -> ReviewSource:
        return await self._source_repo.create(
            organization_id=organization_id,
            name=data.name,
            source_type=data.source_type,
            config=data.config,
        )

    async def list_sources(
        self, organization_id: uuid.UUID, include_inactive: bool = False
    ) -> list[ReviewSource]:
        return await self._source_repo.list_all(
            organization_id=organization_id,
            include_inactive=include_inactive,
        )

    async def get_source(
        self, organization_id: uuid.UUID, source_id: uuid.UUID
    ) -> ReviewSource:
        """
        Fetch a source by id, scoped to the org.
        BaseRepository.get_by_id returns None if the id belongs to a different org —
        the service converts that into a NotFoundError (404).
        """
        source = await self._source_repo.get_by_id(
            id=source_id, organization_id=organization_id
        )
        if not source:
            raise NotFoundError("Source not found.")
        return source

    async def update_source(
        self,
        organization_id: uuid.UUID,
        source_id: uuid.UUID,
        data: SourceUpdate,
    ) -> ReviewSource:
        source = await self.get_source(organization_id, source_id)
        return await self._source_repo.update(
            source=source,
            name=data.name,
            config=data.config,
        )

    async def delete_source(
        self, organization_id: uuid.UUID, source_id: uuid.UUID
    ) -> None:
        """
        Business rule from ENTITIES.md:
        - If the source has no reviews → hard delete (remove the row entirely)
        - If the source has reviews → soft deactivate (is_active = False)

        This prevents orphaning existing reviews while still letting admins
        "remove" a source from the active list.
        """
        source = await self.get_source(organization_id, source_id)
        if await self._source_repo.has_reviews(source.id):
            await self._source_repo.soft_delete(source)
        else:
            await self._source_repo.hard_delete(source)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def ingest(
        self,
        organization_id: uuid.UUID,
        source_id: uuid.UUID,
        file_bytes: bytes | None,
    ) -> IngestResponse:
        """
        Ingest reviews from a source.

        Validation order (fail fast):
        1. Source must exist in this org (get_source raises 404 if not)
        2. Source must be active (raises 409 Conflict if inactive)
        3. Provider parses the raw data into ReviewRows
        4. Repo bulk-inserts, deduplicating on external_id
        """
        source = await self.get_source(organization_id, source_id)

        if not source.is_active:
            raise ConflictError("Cannot ingest into an inactive source.")

        rows = await self._source_provider.ingest(file_bytes)

        # Count rows the provider already dropped (empty content before repo layer).
        # We don't surface these separately — they're included in skipped_count.
        ingested, skipped = await self._review_repo.create_bulk(
            organization_id=organization_id,
            source_id=source_id,
            rows=rows,
        )

        return IngestResponse(
            source_id=source_id,
            ingested_count=ingested,
            skipped_count=skipped,
        )

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    async def list_reviews(
        self,
        organization_id: uuid.UUID,
        source_id: uuid.UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        rating_max: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Review]]:
        """
        Validate the source belongs to this org, then delegate to the repo.
        Raising 404 here is important: it prevents leaking whether a source_id
        exists at all in another org.
        """
        await self.get_source(organization_id, source_id)
        return await self._review_repo.list_by_source(
            organization_id=organization_id,
            source_id=source_id,
            date_from=date_from,
            date_to=date_to,
            rating_max=rating_max,
            limit=limit,
            offset=offset,
        )
