"""Pure text and CSV processing plugins."""
import csv
import io

from ...domain.models import DocumentSource, ParsedDocument, ChunkRecord
from ...domain.policies import normalized_extension


class TextParser:
    extensions = frozenset(("", "txt", "md"))

    def parse(self, source: DocumentSource) -> ParsedDocument:
        for encoding in ("utf-8", "gbk", "gb18030"):
            try:
                return ParsedDocument(source.content.decode(encoding), parser="text")
            except UnicodeDecodeError:
                continue
        return ParsedDocument(source.content.decode("utf-8", errors="replace"), parser="text")


class CsvParser:
    extensions = frozenset(("csv",))

    def parse(self, source: DocumentSource) -> ParsedDocument:
        text = TextParser().parse(source).text
        if not text.strip():
            return ParsedDocument("", parser="csv")
        first = text.splitlines()[0] if text.splitlines() else ""
        delimiter = max((",", "\t", ";"), key=first.count)
        rows = []
        try:
            for row in csv.reader(io.StringIO(text), delimiter=delimiter):
                cells = [cell.strip() for cell in row if cell and cell.strip()]
                if cells:
                    rows.append(" | ".join(cells))
        except csv.Error as exc:
            raise ValueError("CSV 文件格式无效") from exc
        return ParsedDocument("\n".join(rows), parser="csv")


class ParserRegistry:
    def __init__(self, parsers=()):
        self._parsers = []
        for parser in parsers:
            self.register(parser)

    def register(self, parser) -> None:
        self._parsers.append(parser)

    def parse(self, source: DocumentSource) -> ParsedDocument:
        ext = normalized_extension(source.filename)
        for parser in self._parsers:
            if ext in parser.extensions:
                return parser.parse(source)
        raise ValueError(f"不支持的文件格式: {ext or 'unknown'}")


class GenericChunker:
    def __init__(self, max_chars: int | None = None):
        if max_chars is not None and max_chars <= 0:
            raise ValueError("max_chars 必须为正数")
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source: DocumentSource) -> list[ChunkRecord]:
        text = document.text.strip()
        if not text:
            return []
        result = []
        for paragraph in (part.strip() for part in text.split("\n\n")):
            if not paragraph:
                continue
            if self.max_chars is None:
                result.append(ChunkRecord(paragraph))
                continue
            while len(paragraph) > self.max_chars:
                cut = max((paragraph.rfind(mark, 0, self.max_chars)
                           for mark in "。！？!?；;"), default=-1)
                cut = cut + 1 if cut >= self.max_chars // 2 else self.max_chars
                result.append(ChunkRecord(paragraph[:cut].strip()))
                paragraph = paragraph[cut:].strip()
            if paragraph:
                result.append(ChunkRecord(paragraph))
        return result
