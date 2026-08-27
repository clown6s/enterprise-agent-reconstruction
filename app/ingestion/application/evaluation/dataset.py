import json
from pathlib import Path
from .models import RetrievalCase


def load_cases(path: str | Path) -> list[RetrievalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("评测集必须是数组")
    cases = []
    for item in data:
        if not isinstance(item, dict) or not item.get("id") or not item.get("query"):
            raise ValueError("评测用例必须包含非空 id 和 query")
        ids = item.get("relevant_chunk_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError(f"用例 {item['id']} 必须包含 relevant_chunk_ids")
        cases.append(RetrievalCase(item["id"], item["query"], frozenset(ids),
            tuple(item.get("expected_sections", ())), frozenset(item.get("forbidden_chunk_ids", ()))))
    return cases
