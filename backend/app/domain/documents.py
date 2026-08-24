from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ParseStatus(StrEnum):
    PARSED = "parsed"
    SCANNED = "scanned"
    ENCRYPTED = "encrypted"
    DAMAGED = "damaged"
    UNSUPPORTED = "unsupported"


class ParsedBlock(BaseModel):
    block_id: str
    kind: str
    text: str
    order: int = Field(ge=0)
    table_rows: list[list[str]] | None = None


class ParsedPage(BaseModel):
    page_number: int = Field(ge=1)
    blocks: list[ParsedBlock]


class ParsedDocument(BaseModel):
    schema_version: int = 1
    document_id: UUID
    source_name: str
    media_type: str
    pages: list[ParsedPage]
    status: ParseStatus
    failure_reason: str | None = None
