import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    content: str
    author: str | None
    rating: float | None
    review_date: date | None
    created_at: datetime


class ReviewListResponse(BaseModel):
    """Paginated list response — mirrors the shape documented in API.md."""
    total: int
    limit: int
    offset: int
    items: list[ReviewResponse]
