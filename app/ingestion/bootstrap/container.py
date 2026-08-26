"""Composition root for the offline-capable ingestion core."""
from ..application.ingest_document import IngestDocument
from ..processing.chunker_registry import ChunkerRegistry
from ..processing.classifier import RegistryClassifier
from ..processing.profiles import default_profiles
from ..processing.qa import QaChunker
from ..processing.text import CsvParser, GenericChunker, ParserRegistry, TextParser
from ..processing.parsers.docx import DocxParser


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


def build_ingestion(*, embedder=None, vectors=None, metadata=None, originals=None):
    parser = ParserRegistry([TextParser(), CsvParser(), DocxParser()])
    profiles = default_profiles()
    classifier = RegistryClassifier(profiles)
    chunkers = ChunkerRegistry({"qa": QaChunker(), "generic": GenericChunker()})
    return IngestDocument(
        parser=parser, classifier=classifier, chunker=chunkers,
        embedder=embedder or _NoopEmbedder(), vectors=vectors or _NoopVectors(),
        metadata=metadata or _NoopMetadata(), originals=originals or _NoopOriginals(),
    )
