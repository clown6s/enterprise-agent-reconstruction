import json
from pathlib import Path
from .models import RetrievalCase


def load_cases(path: str | Path) -> list[RetrievalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("评测集必须是数组")
    cases = []
    for item in data:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"].strip() or not isinstance(item.get("query"), str)
                or not item["query"].strip()):
            raise ValueError("评测用例必须包含非空字符串 id 和 query")
        ids = item.get("relevant_chunk_ids")
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(value, str) or not value.strip() for value in ids)):
            raise ValueError(f"用例 {item['id']} 的 relevant_chunk_ids 必须是非空字符串列表")
        sections = item.get("expected_sections", ())
        forbidden = item.get("forbidden_chunk_ids", ())
        if (not isinstance(sections, (list, tuple))
                or any(not isinstance(value, str) or not value.strip() for value in sections)
                or not isinstance(forbidden, (list, tuple, set))
                or any(not isinstance(value, str) or not value.strip() for value in forbidden)):
            raise ValueError(f"用例 {item['id']} 的 section/forbidden ID 格式无效")
        cases.append(RetrievalCase(item["id"].strip(), item["query"].strip(), frozenset(ids),
            tuple(sections), frozenset(forbidden)))
    return cases
