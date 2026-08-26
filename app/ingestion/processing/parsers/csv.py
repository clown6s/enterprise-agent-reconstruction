"""CSV parser."""
import csv
import io

from ...domain.models import DocumentSource, ParsedDocument
from .text import TextParser


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


