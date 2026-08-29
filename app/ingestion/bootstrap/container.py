"""上传核心的统一依赖装配入口。"""
import os
from collections.abc import Sequence

from dotenv import load_dotenv

from ..adapters.milvus_vector_store import MilvusVectorStore
from ..adapters.mysql_metadata_store import MySQLMetadataStore
from ..adapters.siliconflow_embedding import SiliconFlowEmbedder
from ..adapters.siliconflow_reranker import SiliconFlowReranker
from ..adapters.sparse_embedding import LocalSparseEmbedder

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


class ConfigurationError(RuntimeError):
    """生产依赖配置不完整或互相矛盾。"""


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
    def find_by_document_id(self, document_id: str) -> dict | None:
        return None
    def record(self, digest: str, document_id: str, source, chunks: int) -> None:
        return None
    def claim(self, digest: str, document_id: str, source,
              stale_after: int = 1800) -> bool:
        return True
    def delete_by_document_id(self, document_id: str) -> int:
        return 0
    def mark_failed(self, digest: str, document_id: str) -> None:
        return None
def _load_env() -> None:
    """从项目根目录显式加载环境变量，避免依赖调用栈推断路径。"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    load_dotenv(os.path.join(project_root, ".env"))


def build_reranker():
    """按环境变量装配重排序器；未配置 API Key 时返回 None。"""
    _load_env()
    if not os.getenv("SILICONFLOW_API_KEY"):
        return None
    return SiliconFlowReranker(
        os.environ["SILICONFLOW_API_KEY"],
        base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        model=os.getenv("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
    )


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


def build_ingestion(*, embedder=None, vectors=None, metadata=None, originals=None,
                    mode: str = "production"):
    if mode not in {"production", "test", "offline"}:
        raise ConfigurationError("mode 必须是 production、test 或 offline")
    _load_env()
    parser = build_parser()
    classifier = RegistryClassifier(default_profiles())
    chunkers = build_chunkers()
    # 生产配置必须成组出现，避免“看似成功但数据没有保存”。
    has_key = bool(os.getenv("SILICONFLOW_API_KEY"))
    has_milvus = bool(os.getenv("MILVUS_HOST"))
    # 真实依赖必须成组出现；禁止自定义依赖与 no-op 实现混用。
    effective_embedder = embedder is not None or has_key
    effective_vectors = vectors is not None or has_milvus
    if mode == "production" and not (effective_embedder and effective_vectors):
        raise ConfigurationError("生产模式必须配置真实 Embedding 与向量库")
    if effective_embedder != effective_vectors:
        raise ConfigurationError("Embedding 与向量库必须同时配置")
    if effective_embedder and not (metadata is not None or os.getenv("MYSQL_HOST")):
        raise ConfigurationError("Embedding、向量库与元数据存储必须同时配置")
    if (has_key or has_milvus) and has_key != has_milvus:
        raise ConfigurationError("SILICONFLOW_API_KEY 与 MILVUS_HOST 必须同时配置")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "4096"))
    if embedding_dim <= 0:
        raise ConfigurationError("EMBEDDING_DIM 必须为正数")
    # 配置了 SiliconFlow Key 时启用真实 Embedding，否则回退到占位实现。
    if embedder is None and has_key:
        embedder = SiliconFlowEmbedder(
            os.environ["SILICONFLOW_API_KEY"],
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            model=os.getenv("SILICONFLOW_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            embedding_dim=embedding_dim,
        )
    # 配置了 Milvus 地址时启用真实向量库，否则回退到占位实现。
    if vectors is None and os.getenv("MILVUS_HOST"):
        vectors = MilvusVectorStore(
            host=os.environ["MILVUS_HOST"], port=int(os.getenv("MILVUS_PORT", "19530")),
            database=os.getenv("MILVUS_DB", "default"),
            collection=os.getenv("MILVUS_COLLECTION", "document_chunks_4096"),
            embedding_dim=embedding_dim, hybrid=True,
        )
    if metadata is None and os.getenv("MYSQL_HOST"):
        metadata = MySQLMetadataStore(
            host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", "")),
            database=os.getenv("MYSQL_DB", "enterprise_agent"),
            min_pool=int(os.getenv("MYSQL_POOL_MIN", "1")),
            max_pool=int(os.getenv("MYSQL_POOL_MAX", "8")),
        )
    return IngestDocument(
        parser=parser, classifier=classifier, chunker=chunkers,
        embedder=embedder or _NoopEmbedder(), sparse_embedder=LocalSparseEmbedder(),
        vectors=vectors or _NoopVectors(),
        metadata=metadata or _NoopMetadata(),
        embedding_dim=embedding_dim,
    )