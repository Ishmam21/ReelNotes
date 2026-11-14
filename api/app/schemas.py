from pydantic import BaseModel, Field, ConfigDict

class PlaylistCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)

class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)

from datetime import datetime
from uuid import UUID
from .guide import Extraction, ExtractedClaim, Group, Exclusion, Consolidation

class PlaylistResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime

class PlaylistSummary(PlaylistResponse):
    item_count: int

class VideoCard(BaseModel):
    video_id: UUID
    position: int
    title: str | None
    source_url: str
    thumbnail_url: str | None
    state: str
    error_code: str | None
    error_message: str | None
    claims_count: int | None

class PlaylistDetail(PlaylistResponse):
    items: list[VideoCard]

class GuideResponse(BaseModel):
    id: UUID
    markdown: str
    created_at: datetime

class RetryResponse(BaseModel):
    video_id: UUID
    state: str
