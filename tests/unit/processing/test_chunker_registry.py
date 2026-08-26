from app.ingestion.domain.models import DocumentSource, ParsedDocument, ChunkRecord
from app.ingestion.processing.chunker_registry import ChunkerRegistry, ChunkerSelectionError

class Marker:
    def __init__(self, name): self.name = name
    def chunk(self, document, source): return [ChunkRecord(self.name)]

def test_selects_registered_kind():
    registry = ChunkerRegistry({"qa": Marker("qa"), "generic": Marker("generic")})
    result = registry.chunk("qa", ParsedDocument("x"), DocumentSource("x", b"x"))
    assert result[0].text == "qa"

def test_unknown_kind_uses_generic_fallback():
    registry = ChunkerRegistry({"generic": Marker("generic")})
    assert registry.select("legal").name == "generic"

def test_duplicate_registration_is_rejected():
    registry = ChunkerRegistry({"generic": Marker("one")})
    try:
        registry.register("generic", Marker("two"))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate registration should fail")

def test_missing_fallback_is_explicit():
    registry = ChunkerRegistry()
    try:
        registry.select("qa")
    except ChunkerSelectionError:
        pass
    else:
        raise AssertionError("missing fallback should fail")
