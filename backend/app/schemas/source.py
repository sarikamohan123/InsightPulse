import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.review_source import SourceType


class SourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source_type: SourceType
    config: dict = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    """All fields optional — PATCH semantics."""
    name: str | None = Field(None, min_length=1, max_length=100)
    config: dict | None = None


class SourceListItem(BaseModel):
    """Lightweight shape returned in list responses — config omitted."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    is_active: bool
    created_at: datetime


class SourceResponse(BaseModel):
    """Full shape returned on create, get-by-id, and update."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    source_type: SourceType
    config: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class IngestResponse(BaseModel):
    source_id: uuid.UUID
    ingested_count: int
    skipped_count: int
