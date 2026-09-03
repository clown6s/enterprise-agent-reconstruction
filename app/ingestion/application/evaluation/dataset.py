import json
from pathlib import Path
from .models import RetrievalCase


def _all_nonempty_strings(values) -> bool:
    """判断可迭代对象中的每个元素是否都是非空字符串。"""
    return all(isinstance(value, str) and value.strip() for value in values)


def load_cases(path: str | Path) -> list[RetrievalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("评测集必须是数组")
    cases = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("评测用例必须是对象")
        item_id = item.get("id")
        query = item.get("query")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("评测用例必须包含非空字符串 id")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("评测用例必须包含非空字符串 query")
        ids = item.get("relevant_chunk_ids")
        if not isinstance(ids, list) or not ids or not _all_nonempty_strings(ids):
            raise ValueError(f"用例 {item['id']} 的 relevant_chunk_ids 必须是非空字符串列表")
        sections = item.get("expected_sections", ())
        forbidden = item.get("forbidden_chunk_ids", ())
        if (not isinstance(sections, (list, tuple))
                or not _all_nonempty_strings(sections)
                or not isinstance(forbidden, (list, tuple, set))
                or not _all_nonempty_strings(forbidden)):
            raise ValueError(f"用例 {item['id']} 的 section/forbidden ID 格式无效")
        cases.append(RetrievalCase(item["id"].strip(), item["query"].strip(), frozenset(ids),
            tuple(sections), frozenset(forbidden)))
    return cases
