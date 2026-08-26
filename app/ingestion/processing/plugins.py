"""Default processing plugins, kept independent from infrastructure."""
from ..domain.models import ChunkRecord, DocumentSource, ParsedDocument
from ..domain.policies import normalized_extension


class TextParser:
    extensions = {"", "txt", "md"}
    def parse(self, source: DocumentSource) -> ParsedDocument:
        for encoding in ("utf-8", "gbk", "gb18030"):
            try:
                return ParsedDocument(source.content.decode(encoding), parser="text")
            except UnicodeDecodeError:
                continue
        return ParsedDocument(source.content.decode("utf-8", errors="replace"), parser="text")


class ParserRegistry:
    def __init__(self, parsers=()): self._parsers = list(parsers)
    def register(self, parser): self._parsers.append(parser)
    def parse(self, source):
        ext = normalized_extension(source.filename)
        for parser in self._parsers:
            if ext in parser.extensions:
                return parser.parse(source)
        raise ValueError(f"不支持的文件格式: {ext or 'unknown'}")


class GenericClassifier:
    def classify(self, document: ParsedDocument, source: DocumentSource) -> str:
        return "generic"


class GenericChunker:
    def __init__(self, max_chars=600): self.max_chars = max_chars
    def chunk(self, document: ParsedDocument, source: DocumentSource) -> list[ChunkRecord]:
        text = document.text.strip()
        return [ChunkRecord(text=text)] if text else []
