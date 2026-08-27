from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_chunk_ids: frozenset[str]
    expected_sections: tuple[str, ...] = ()
    forbidden_chunk_ids: frozenset[str] = frozenset()
