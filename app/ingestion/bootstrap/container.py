"""上传核心的统一依赖装配入口（composition root）。

只负责把 parser/chunker/adapter/用例装配起来；
环境加载与配置校验统一委托给 config 模块。
"""
import os
from collections.abc import Sequence

from ..adapters.milvus_vector_store import MilvusVectorStore
from ..adapters.mysql_metadata_store import MySQLMetadataStore
from ..adapters.siliconflow_embedding import SiliconFlowEmbedder
from ..adapters.siliconflow_reranker import SiliconFlowReranker
from ..adapters.elasticsearch_text_store import ElasticsearchTextStore
from ..adapters.elasticsearch_synonyms import ElasticsearchSynonyms

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
from ..processing.structure_analyzer import IdentityStructureAnalyzer

from .config import ConfigurationError, load_env, read_settings, validate_composition

# 兼容旧调用方：ConfigurationError 仍可从 container 模块访问。
__all__ = ["build_ingestion", "build_reranker", "ConfigurationError"]


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
    def claim(self, digest: str, document_id: str, source) -> bool:
        return True
    def delete_by_document_id(self, document_id: str) -> int:
        return 0
    def mark_failed(self, digest: str, document_id: str) -> None:
        return None


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


def build_reranker():
    """按环境配置构造模型 reranker；配置不齐时返回 None（不启用）。"""
    load_env()
    if not os.getenv("SILICONFLOW_API_KEY"):
        return None
    return SiliconFlowReranker(
        os.environ["SILICONFLOW_API_KEY"],
        base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        model=os.getenv("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
    )


def build_ingestion(*, embedder=None, vectors=None, metadata=None, originals=None,
                    mode: str = "production"):
    if mode not in {"production", "test", "offline"}:
        raise ConfigurationError("mode 必须是 production、test 或 offline")
    load_env()
    settings = read_settings()
    validate_composition(mode, settings, embedder=embedder, vectors=vectors,
                         metadata=metadata)

    parser = build_parser()
    classifier = RegistryClassifier(default_profiles())
    chunkers = build_chunkers()

    embedding_dim = settings.embedding_dim
    # 配置了 SiliconFlow Key 时启用真实 Embedding，否则回退到占位实现。
    if embedder is None and settings.has_embedding_key:
        embedder = SiliconFlowEmbedder(
            os.environ["SILICONFLOW_API_KEY"],
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            model=os.getenv("SILICONFLOW_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            embedding_dim=embedding_dim,
        )
    # 配置了 Milvus 地址时启用真实向量库（仅 dense），否则回退到占位实现。
    if vectors is None and settings.has_milvus:
        vectors = MilvusVectorStore(
            host=os.environ["MILVUS_HOST"], port=int(os.getenv("MILVUS_PORT", "19530")),
            database=os.getenv("MILVUS_DB", "default"),
            collection=os.getenv("MILVUS_COLLECTION", "document_chunks_4096"),
            embedding_dim=embedding_dim,
            user=os.getenv("MILVUS_ROOT_USER", ""), password=os.getenv("MILVUS_PASSWORD", ""),
            token=os.getenv("MILVUS_TOKEN", "") or None,
        )
    lexical = None
    synonyms = None
    if settings.has_es:
        synonyms_set = os.getenv("ES_SYNONYMS_SET", "enterprise-retrieval-synonyms")
        lexical = ElasticsearchTextStore(
            host=os.environ["ES_HOST"], index=os.environ["ES_INDEX"],
            username=os.getenv("ES_USERNAME", ""), password=os.getenv("ES_PASSWORD", ""),
            cert_fingerprint=os.getenv("CERT_FINGERPRINT", ""),
            timeout=float(os.getenv("ES_TIMEOUT", "10")),
            synonyms_set=synonyms_set,
        )
        synonyms = ElasticsearchSynonyms(
            host=os.environ["ES_HOST"], index=os.environ["ES_INDEX"],
            username=os.getenv("ES_USERNAME", ""), password=os.getenv("ES_PASSWORD", ""),
            cert_fingerprint=os.getenv("CERT_FINGERPRINT", ""),
            timeout=float(os.getenv("ES_TIMEOUT", "10")),
            synonyms_set=synonyms_set,
        )
    if metadata is None and settings.has_mysql:
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
        embedder=embedder or _NoopEmbedder(),
        vectors=vectors or _NoopVectors(),
        metadata=metadata or _NoopMetadata(),
        lexical=lexical,
        synonyms=synonyms,
        embedding_dim=embedding_dim,
        structure_analyzer=IdentityStructureAnalyzer(),
    )
