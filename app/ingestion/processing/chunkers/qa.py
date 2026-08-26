"""Question-and-answer document profile and paired chunker."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_QUESTION = re.compile(r"^\s*(\d+)[、.．]\s*(.+)$")
_ANSWER = re.compile(r"^\s*(?:答|答案|解析)\s*[:：]\s*(.*)$")
_SECTION = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千万]+[、.．]|##\s*).+")


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


def qa_confidence(document: ParsedDocument) -> dict:
    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    questions = sum(bool(_QUESTION.match(line)) for line in lines)
    answers = sum(bool(_ANSWER.match(line)) for line in lines)
    confidence = min(1.0, (questions + answers) / max(1, len(lines)) * 2)
    return {"kind": "qa" if questions >= 2 and answers >= 1 else "generic",
            "confidence": confidence, "question_count": questions,
            "answer_count": answers}


class QaClassifier:
    def classify(self, document: ParsedDocument, source=None) -> str:
        return "qa" if qa_confidence(document)["kind"] == "qa" else "generic"


class QaChunker:
    def __init__(self, max_chars: int = 600):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        units: list[ChunkRecord] = []
        current: list[str] = []
        section = ""
        number = None

        def flush():
            nonlocal current, number
            body = " ".join(line.strip() for line in current if line.strip())
            if body:
                paired = any(_ANSWER.match(line.strip()) for line in current)
                metadata = {"kind": "qa", "question_number": number,
                            "qa_status": "paired" if paired else "unknown"}
                parts = _split_long(body, self.max_chars)
                for part_index, part in enumerate(parts):
                    if part:
                        units.append(ChunkRecord(
                            text=part, kind="qa", section_path=(section,) if section else (),
                            continuation=part_index > 0,
                            continuation_of=f"qa:{number}" if number is not None else None,
                            continuation_index=part_index, metadata=metadata))
            current.clear()
            number = None

        for raw in document.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if re.fullmatch(r"\[\[page:(\d+)\]\]", line):
                continue
            if _SECTION.match(line) and not _QUESTION.match(line):
                flush(); section = line; continue
            if _QUESTION.match(line):
                flush(); number = int(_QUESTION.match(line).group(1)); current.append(line); continue
            if current:
                current.append(line)
            else:
                units.append(ChunkRecord(line, kind="qa", section_path=(section,) if section else (), metadata={"qa_status": "unknown"}))
        flush()
        return units
