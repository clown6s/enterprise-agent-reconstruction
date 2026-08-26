from app.ingestion.application.ingest_document import IngestDocument
from app.ingestion.domain.models import ChunkRecord, DocumentSource, ParsedDocument, IngestionStatus

class Parser:
    def parse(self, source): return ParsedDocument("正文")
class Classifier:
    def classify(self, document, source): return "generic"
class Chunker:
    def chunk(self, kind, document, source): return [ChunkRecord(document.text)]
class Embedder:
    def __init__(self): self.calls = 0
    def embed_batch(self, texts): self.calls += 1; return [[0.1]]
class Vectors:
    def __init__(self): self.rows = []
    def has_document(self, doc_id): return False
    def insert(self, rows): self.rows.extend(rows); return True
class Metadata:
    def __init__(self): self.records = []
    def find_by_sha(self, digest): return None
    def record(self, *args): self.records.append(args)
class Originals:
    def __init__(self): self.calls = 0
    def archive(self, digest, source): self.calls += 1
class Events:
    def __init__(self): self.events = []
    def publish(self, event): self.events.append(event)

def make():
    deps = Parser(), Classifier(), Chunker(), Embedder(), Vectors(), Metadata(), Originals(), Events()
    return IngestDocument(*deps[:-1], events=deps[-1]), deps

def test_upload_use_case_is_offline_and_composable():
    service, deps = make()
    result = service.execute(DocumentSource("a.txt", b"content", title="A"))
    assert result.status == IngestionStatus.INGESTED
    assert deps[3].calls == 1 and len(deps[4].rows) == 1
    assert len(deps[5].records) == 1 and deps[6].calls == 1
    assert deps[7].events[0]["type"] == "DocumentIngested"

def test_size_rejection_has_no_side_effect():
    service, deps = make()
    service.max_file_bytes = 1
    result = service.execute(DocumentSource("big.txt", b"12345"))
    assert result.status == IngestionStatus.REJECTED
    assert deps[3].calls == 0 and not deps[4].rows and not deps[5].records
