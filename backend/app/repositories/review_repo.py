import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.review import Review
from app.repositories.base import BaseRepository


@dataclass
class ReviewRow:
    """
    Intermediate data structure that carries a single parsed review
    from a SourceProvider to the ReviewRepository.

    Using a dataclass (not a Pydantic model) here because this is an
    internal transfer object — it never crosses an HTTP boundary.
    """
    content: str
    external_id: str | None = None
    author: str | None = None
    rating: float | None = None
    review_date: date | None = None
    raw_metadata: dict | None = None


class ReviewRepository(BaseRepository[Review]):
    model = Review

    async def create_bulk(
        self,
        organization_id: uuid.UUID,
        source_id: uuid.UUID,
        rows: list[ReviewRow],
    ) -> tuple[int, int]:
        """
        Insert a batch of reviews, skipping duplicates.

        Duplicate detection strategy:
        - First collect all external_ids already in the DB for this source.
        - Skip any incoming row whose external_id is already present.
        - For rows without an external_id we always insert (no dedup possible).
        - Any remaining IntegrityError (race condition) is caught per-row.

        Returns (ingested_count, skipped_count).
        """
        # Fetch existing external_ids for this source in one query.
        existing_result = await self.session.execute(
            select(Review.external_id).where(
                Review.source_id == source_id,
                Review.external_id.isnot(None),
            )
        )
        existing_ids: set[str] = {row for (row,) in existing_result.all()}

        ingested = 0
        skipped = 0

        for row in rows:
            # Skip rows that are already in the DB.
            if row.external_id and row.external_id in existing_ids:
                skipped += 1
                continue

            review = Review(
                organization_id=organization_id,
                source_id=source_id,
                external_id=row.external_id,
                content=row.content,
                author=row.author,
                rating=row.rating,
                review_date=row.review_date,
                raw_metadata=row.raw_metadata,
            )
            try:
                # begin_nested() issues a SAVEPOINT. On IntegrityError, only this
                # savepoint is rolled back — the outer transaction (and all previously
                # ingested rows) remains intact. This is essential in tests where the
                # whole test runs inside one transaction managed by the test_db fixture.
                async with self.session.begin_nested():
                    self.session.add(review)
                ingested += 1
                # Track newly inserted external_id to catch intra-batch duplicates.
                if row.external_id:
                    existing_ids.add(row.external_id)
            except IntegrityError:
                # Savepoint was rolled back automatically — outer transaction is safe.
                skipped += 1

        return ingested, skipped

    async def list_by_source(
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
        Return a paginated, filtered list of reviews.
        Also returns the total count so the API can include it in the response.
        """
        base_filter = [
            Review.organization_id == organization_id,
            Review.source_id == source_id,
        ]
        if date_from:
            base_filter.append(Review.review_date >= date_from)
        if date_to:
            base_filter.append(Review.review_date <= date_to)
        if rating_max is not None:
            base_filter.append(Review.rating <= rating_max)

        # Count query — same filters, no pagination.
        count_result = await self.session.execute(
            select(func.count()).select_from(Review).where(*base_filter)
        )
        total: int = count_result.scalar_one()

        # Data query — with pagination.
        items_result = await self.session.execute(
            select(Review)
            .where(*base_filter)
            .order_by(Review.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(items_result.scalars().all())

        return total, items
