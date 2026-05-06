import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_organization_id, get_review_service
from app.schemas.review import ReviewListResponse, ReviewResponse
from app.services.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    source_id: uuid.UUID = Query(..., description="Required — filter to a specific source"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    rating_max: float | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
) -> ReviewListResponse:
    total, items = await service.list_reviews(
        organization_id=organization_id,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        rating_max=rating_max,
        limit=limit,
        offset=offset,
    )
    return ReviewListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[ReviewResponse.model_validate(r) for r in items],
    )
