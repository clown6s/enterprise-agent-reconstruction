"""通用 PDF 页面噪声清理。"""
import re


_HEADING = re.compile(
    r"^(?:第\s*[0-9一二三四五六七八九十百千万]+\s*章|"
    r"[1-9]\d*(?:\.\d+){1,3})\s+.+$"
)


def repeated_margin_lines(texts: list[str], *, top: bool) -> set[str]:
    counts = {}
    for text in texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in set(lines[:2] if top else lines[-2:]):
            counts[line] = counts.get(line, 0) + 1
    return {line for line, count in counts.items() if count >= 3 and len(line) <= 120}


def remove_positioned_header(lines, positioned_lines, height):
    if not positioned_lines or not height:
        return lines
    candidates = {text.strip() for text, top in positioned_lines if top <= height * 0.12}
    if not candidates:
        return lines
    top_text = " ".join(candidates)
    has_section_number = bool(re.search(r"(?:第\s*[0-9一二三四五六七八九十百千万]+\s*章|[1-9]\d*(?:\.\d+){1,3})", top_text))
    if has_section_number and lines and _HEADING.fullmatch(lines[0].strip()):
        return lines[1:]
    for candidate in candidates:
        if candidate in {line.strip() for line in lines[1:]}:
            for index, line in enumerate(lines[:3]):
                if line.strip() == candidate:
                    return lines[:index] + lines[index + 1:]
    return lines


def remove_margin_lines(lines, candidates: set[str], *, top: bool):
    indexes = set(range(min(2, len(lines))) if top else range(max(0, len(lines) - 2), len(lines)))
    return [line for index, line in enumerate(lines) if not (index in indexes and line.strip() in candidates)]


def remove_inline_page_number(lines, page_number: int):
    return [re.sub(rf"\s+{page_number}\s*$", "", line) for line in lines]
