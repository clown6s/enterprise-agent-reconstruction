"""上传核心的统一依赖装配入口。"""
import os
from collections.abc import Sequence

from dotenv import load_dotenv

from ..domain.models import DocumentSource

from ..adapters.milvus_vector_store import MilvusVectorStore
from ..adapters.siliconflow_embedding import SiliconFlowEmbedder

from ..application.ingest_document import IngestDocument
from ..processing.chunker_registry import ChunkerRegistry
from ..processing.classifier import RegistryClassifier
from ..processing.profiles import default_profiles
from ..processing.chunkers.legal import LegalChunker
from ..processing.chunkers.generic import GenericChunker
from ..processing.chunkers.qa import QaChunker
from ..processing.chunkers.technical import TechnicalChunker
from ..processing.chunkers.medical import MedicalChunker
from ..processing.parsers.csv import CsvParser
from ..processing.parsers.registry import ParserRegistry
from ..processing.parsers.text import TextParser
from ..processing.parsers.docx import DocxParser
from ..processing.parsers.pdf import PdfParser


class _NoopEmbedder:
    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]
class _NoopVectors:
    def has_document(self, document_id: str) -> bool:
        return False
    def insert(self, rows: list[dict]) -> bool:
        return True
    def delete(self, document_id: str) -> int:
        return 0
class _NoopMetadata:
    def find_by_sha(self, digest: str) -> dict | None:
        return None
    def record(self, digest: str, document_id: str, source: DocumentSource, chunks: int) -> None:
        return None
class _NoopOriginals:
    def archive(self, digest: str, source: DocumentSource) -> None:
        return None


def _load_env() -> None:
    """从项目根目录显式加载环境变量，避免依赖调用栈推断路径。"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    load_dotenv(os.path.join(project_root, ".env"))


def build_parser():
    return ParserRegistry([TextParser(), CsvParser(), DocxParser(), PdfParser()])


def build_chunkers():
    return ChunkerRegistry({
        "qa": QaChunker(),
        "legal": LegalChunker(),
        "technical_book": TechnicalChunker(),
        "medical_book": MedicalChunker(),
        "generic": GenericChunker(),
    })


def build_ingestion(*, embedder=None, vectors=None, metadata=None, originals=None):
    _load_env()
    parser = build_parser()
    classifier = RegistryClassifier(default_profiles())
    chunkers = build_chunkers()
    # 配置了 SiliconFlow Key 时启用真实 Embedding，否则回退到占位实现。
    if embedder is None and os.getenv("SILICONFLOW_API_KEY"):
        embedder = SiliconFlowEmbedder(
            os.environ["SILICONFLOW_API_KEY"],
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            model=os.getenv("SILICONFLOW_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "4096")),
        )
    # 配置了 Milvus 地址时启用真实向量库，否则回退到占位实现。
    if vectors is None and os.getenv("MILVUS_HOST"):
        vectors = MilvusVectorStore(
            host=os.environ["MILVUS_HOST"], port=int(os.getenv("MILVUS_PORT", "19530")),
            database=os.getenv("MILVUS_DB", "default"),
            collection=os.getenv("MILVUS_COLLECTION", "document_chunks_4096"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "4096")),
        )
    return IngestDocument(
        parser=parser, classifier=classifier, chunker=chunkers,
        embedder=embedder or _NoopEmbedder(), vectors=vectors or _NoopVectors(),
        metadata=metadata or _NoopMetadata(), originals=originals or _NoopOriginals(),
    )
