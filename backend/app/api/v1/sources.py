import uuid

from fastapi import APIRouter, Depends, Query, UploadFile

from app.api.deps import get_organization_id, get_review_service, require_admin
from app.schemas.source import (
    IngestResponse,
    SourceCreate,
    SourceListItem,
    SourceResponse,
    SourceUpdate,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    body: SourceCreate,
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
    _admin=Depends(require_admin),
) -> SourceResponse:
    source = await service.create_source(organization_id, body)
    return SourceResponse.model_validate(source)


@router.get("", response_model=list[SourceListItem])
async def list_sources(
    include_inactive: bool = Query(False),
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
) -> list[SourceListItem]:
    sources = await service.list_sources(organization_id, include_inactive)
    return [SourceListItem.model_validate(s) for s in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
) -> SourceResponse:
    source = await service.get_source(organization_id, source_id)
    return SourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
    _admin=Depends(require_admin),
) -> SourceResponse:
    source = await service.update_source(organization_id, source_id, body)
    return SourceResponse.model_validate(source)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
    _admin=Depends(require_admin),
) -> None:
    await service.delete_source(organization_id, source_id)


@router.post("/{source_id}/ingest", response_model=IngestResponse, status_code=201)
async def ingest(
    source_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_organization_id),
    service: ReviewService = Depends(get_review_service),
    _admin=Depends(require_admin),
    file: UploadFile | None = None,
) -> IngestResponse:
    file_bytes = await file.read() if file else None
    return await service.ingest(organization_id, source_id, file_bytes)
