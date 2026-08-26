"""Dependency-free ingestion domain models."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OcrStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class IngestionStatus(str, Enum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    PENDING = "pending"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class DocumentSource:
    filename: str
    content: bytes
    content_type: str | None = None
    title: str = ""
    tags: str = ""
    origin: str = "http"
    external_id: str | None = None

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class LayoutBlock:
    text: str
    kind: str | None = None
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    layout_blocks: tuple[LayoutBlock, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    profile: str | None = None
    parser: str | None = None


@dataclass(frozen=True)
class ChunkRecord:
    text: str
    kind: str = "prose"
    page: int = 1
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    continuation: bool = False
    continuation_of: str | None = None
    continuation_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OcrTask:
    task_id: str
    status: OcrStatus
    parsed: ParsedDocument | None = None


@dataclass(frozen=True)
class IngestionResult:
    status: IngestionStatus
    filename: str
    size: int
    document_id: str | None = None
    chunks: int = 0
    task_id: str | None = None
    ocr_status: OcrStatus | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    message: str | None = None
