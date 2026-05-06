import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Review(Base):
    __tablename__ = "reviews"

    # Unique constraint: same external review cannot be ingested twice for the same source.
    # This is the deduplication guard at the DB level — the service layer also enforces it,
    # but having it here means the DB will reject a race condition too.
    __table_args__ = (
        UniqueConstraint("external_id", "source_id", name="uq_review_external_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: not all platforms give us a stable ID for each review.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Required — rows without content are rejected at the service layer.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Full original payload kept for audit/debug — never queried, just stored.
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    source: Mapped["ReviewSource"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ReviewSource", back_populates="reviews", lazy="noload"
    )
