"""Pluggable chunker selection by classified document kind."""
from collections.abc import Mapping

from ..domain.exceptions import ValidationError
from ..domain.models import ChunkRecord, DocumentSource, ParsedDocument


class ChunkerSelectionError(ValidationError):
    """Raised when no fallback chunker is configured."""


class ChunkerRegistry:
    def __init__(self, chunkers: Mapping[str, object] | None = None,
                 *, fallback_key: str = "generic"):
        self._chunkers: dict[str, object] = {}
        self.fallback_key = fallback_key
        for key, chunker in (chunkers or {}).items():
            self.register(key, chunker)

    def register(self, kind: str, chunker: object) -> None:
        key = kind.strip()
        if not key:
            raise ValueError("切分器 key 不能为空")
        if key in self._chunkers:
            raise ValueError(f"重复注册切分器: {key}")
        if not callable(getattr(chunker, "chunk", None)):
            raise TypeError(f"切分器 {key} 必须提供 chunk()")
        self._chunkers[key] = chunker

    def select(self, kind: str):
        chunker = self._chunkers.get(kind) or self._chunkers.get(self.fallback_key)
        if chunker is None:
            raise ChunkerSelectionError(f"未配置切分器: {kind}")
        return chunker

    def chunk(self, kind: str, document: ParsedDocument,
              source: DocumentSource) -> list[ChunkRecord]:
        return self.select(kind).chunk(document, source)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._chunkers)
