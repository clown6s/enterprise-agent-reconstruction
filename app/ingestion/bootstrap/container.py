"""上传核心的统一依赖装配入口。"""
import os

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
    def embed_batch(self, texts): return [[0.0] for _ in texts]
class _NoopVectors:
    def has_document(self, document_id): return False
    def insert(self, rows): return True
    def delete(self, document_id): return 0
class _NoopMetadata:
    def find_by_sha(self, digest): return None
    def record(self, *args): pass
class _NoopOriginals:
    def archive(self, digest, source): pass


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
    parser = build_parser()
    classifier = RegistryClassifier(default_profiles())
    chunkers = build_chunkers()
    return IngestDocument(
        parser=parser, classifier=classifier, chunker=chunkers,
        embedder=embedder or _NoopEmbedder(), vectors=vectors or _NoopVectors(),
        metadata=metadata or _NoopMetadata(), originals=originals or _NoopOriginals(),
    )
