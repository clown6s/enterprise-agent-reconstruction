"""Pure text parsing plugin."""
from ...domain.models import DocumentSource, ParsedDocument


class TextParser:
    extensions = frozenset(("", "txt", "md"))

    def parse(self, source: DocumentSource) -> ParsedDocument:
        for encoding in ("utf-8", "gbk", "gb18030"):
            try:
                return ParsedDocument(source.content.decode(encoding), parser="text")
            except UnicodeDecodeError:
                continue
        return ParsedDocument(source.content.decode("utf-8", errors="replace"), parser="text")
