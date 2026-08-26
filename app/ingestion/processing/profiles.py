"""Extensible, dependency-free document profile detection."""
import re
from dataclasses import dataclass
from typing import Callable

from ..domain.models import ParsedDocument


@dataclass(frozen=True)
class Classification:
    kind: str
    confidence: float
    evidence: tuple[str, ...] = ()


def _legal(document):
    text = document.text
    articles = len(re.findall(r"^\s*第\s*[0-9零一二三四五六七八九十百千万]+\s*条", text, re.M))
    return Classification("legal", min(0.95, articles / 10), ("article_structure",)) if articles >= 5 else Classification("legal", 0)


def _medical_book(document):
    text = document.text
    signals = sum(bool(re.search(pattern, text, re.I)) for pattern in (
        "内科学", "疾病", "诊断", "治疗", "症状", "病理", "临床",
    ))
    return Classification("medical_book", min(0.95, signals / 4), ("medical_signals",)) if signals >= 3 else Classification("medical_book", 0)


def _structured_book(document):
    text = document.text
    signals = sum(bool(re.search(pattern, text, re.I)) for pattern in ("目录", r"第\s*\d+\s*章", "API", "代码", "函数", "模块", "```") )
    return Classification("technical_book", min(0.95, signals / 5), ("technical_signals",))


def _qa(document):
    from .chunkers.qa import qa_confidence
    info = qa_confidence(document)
    return Classification("qa", info["confidence"], ("question_answer_pairs",)) if info["kind"] == "qa" else Classification("qa", 0)


def _generic(document):
    return Classification("generic", 0, ("fallback",))


class ProfileRegistry:
    def __init__(self, profiles: list[tuple[str, Callable]] | None = None):
        self._profiles = list(profiles or [])

    def register(self, name: str, detector: Callable) -> None:
        if any(existing == name for existing, _ in self._profiles):
            raise ValueError(f"重复注册文档 profile: {name}")
        self._profiles.append((name, detector))

    def classify(self, document: ParsedDocument) -> Classification:
        candidates = [detector(document) for _, detector in self._profiles]
        candidates = [item for item in candidates if item.confidence > 0]
        if not candidates:
            return _generic(document)
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        if candidates[0].confidence < 0.65:
            return _generic(document)
        if len(candidates) > 1 and candidates[0].confidence - candidates[1].confidence < 0.10:
            return Classification("generic", candidates[0].confidence, ("ambiguous",))
        return candidates[0]


def default_profiles() -> ProfileRegistry:
    registry = ProfileRegistry()
    registry.register("legal", _legal)
    registry.register("medical_book", _medical_book)
    registry.register("technical_book", _structured_book)
    registry.register("qa", _qa)
    return registry
