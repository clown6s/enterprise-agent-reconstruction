"""Deterministic query analysis for retrieval routing and ranking."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QueryProfile:
    kind: str
    exact_terms: tuple[str, ...] = ()
    section_terms: tuple[str, ...] = ()


_ARTICLE = re.compile(r"第\s*[0-9零一二三四五六七八九十百千万]+\s*条")
_EXPERIMENT = re.compile(r"实验\s*[0-9]+(?:\s*[-—]\s*[0-9]+)?")
_SECTION = re.compile(r"(?:第\s*[0-9零一二三四五六七八九十百千万]+\s*[章节篇]|\b[0-9]+(?:\.[0-9]+)+\b)")
_TERM = re.compile(r"(?<![A-Za-z])[A-Z][A-Za-z0-9]*(?:[@^][A-Za-z0-9]+)?\b")


def analyze_query(query: str) -> QueryProfile:
    """Classify query intent without model/database dependencies."""
    exact = _unique(m.group(0).strip() for pattern in (_ARTICLE, _EXPERIMENT) for m in pattern.finditer(query))
    sections = _unique(m.group(0).strip() for m in _SECTION.finditer(query))
    terms = _unique(m.group(0).strip() for m in _TERM.finditer(query))
    exact = _unique((*exact, *terms))
    if sections:
        kind = "section"
    elif exact and any(_ARTICLE.search(item) or _EXPERIMENT.search(item) for item in exact):
        kind = "exact"
    else:
        kind = "semantic"
    return QueryProfile(kind, exact, sections)


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
