"""Question-and-answer document profile and paired chunker."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_QUESTION = re.compile(r"^\s*(\d+)[、.．]\s*(.+)$")
_ANSWER = re.compile(r"^\s*(?:答|答案|解析)\s*[:：]\s*(.*)$")
_SECTION = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千万]+[、.．]|##\s*).+")


def qa_confidence(document: ParsedDocument) -> dict:
    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    questions = sum(bool(_QUESTION.match(line)) and ("？" in line or "?" in line or
                     bool(re.search(r"什么|哪里|如何|为什么|哪些|多少|谁|何时|吗", line)))
                    for line in lines)
    answers = sum(bool(_ANSWER.match(line)) for line in lines)
    confidence = min(1.0, questions / max(1, len(lines)) * 2 +
                     answers / max(1, len(lines)) * 2)
    return {"kind": "qa" if questions >= 5 and answers >= 3 else "generic",
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
                for part_index, start in enumerate(range(0, len(body), self.max_chars)):
                    part = body[start:start + self.max_chars].strip()
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
