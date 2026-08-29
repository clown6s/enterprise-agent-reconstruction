"""无外部依赖的文档摄取领域模型。"""
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
class ContentBlock:
    """解析后的内容及其版面事实；结构 metadata 不绑定任何存储实现。"""
    text: str
    kind: str | None = None
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# 兼容现有 parser/chunker 调用方；新代码优先使用 ContentBlock。
LayoutBlock = ContentBlock


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
class VectorSearchRequest:
    """与具体向量数据库无关的检索请求。"""
    dense_vector: tuple[float, ...] = ()
    sparse_vector: tuple[tuple[int, float], ...] = ()
    top_k: int = 10
    document_id: str | None = None
    section: str | None = None
    article: str | None = None
    # 服务端全文检索（如 BM25 Function）时直接传查询原文，分词与加权由向量库完成。
    sparse_text: str | None = None

    def __post_init__(self):
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValueError("top_k 必须是正整数")


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
