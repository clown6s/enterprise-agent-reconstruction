"""Parser registry."""
from ...domain.models import DocumentSource, ParsedDocument
from ...domain.policies import normalized_extension


class ParserRegistry:
    def __init__(self, parsers=()):
        self._parsers = []
        for parser in parsers:
            self.register(parser)

    def register(self, parser) -> None:
        self._parsers.append(parser)

    def for_profile(self, profile: str | None):
        specialized = [getattr(parser, "for_profile", lambda _: parser)(profile)
                       for parser in self._parsers]
        # 没有任何 parser 针对该 profile 特化时，返回自身，避免无意义的二次解析。
        if all(s is p for s, p in zip(specialized, self._parsers)):
            return self
        selected = ParserRegistry()
        selected._parsers = specialized
        return selected

    def parse(self, source: DocumentSource) -> ParsedDocument:
        ext = normalized_extension(source.filename)
        for parser in self._parsers:
            if ext in parser.extensions:
                return parser.parse(source)
        raise ValueError(f"不支持的文件格式: {ext or 'unknown'}")


