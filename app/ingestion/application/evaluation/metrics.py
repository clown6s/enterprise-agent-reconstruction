def result_id(result):
    return (result.metadata or {}).get("chunk_id")


def hit_rate_at_k(ids, relevant, k):
    return float(bool(set(ids[:k]) & set(relevant)))


def recall_at_k(ids, relevant, k):
    relevant = set(relevant)
    return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0


def reciprocal_rank(ids, relevant):
    relevant = set(relevant)
    for rank, item in enumerate(ids, 1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def noise_rate(ids, forbidden, k):
    returned = ids[:k]
    return sum(item in set(forbidden) for item in returned) / len(returned) if returned else 0.0


def section_hit(results, expected, k):
    expected = set(expected)
    return float(any(expected.intersection(result.section_path) for result in results[:k])) if expected else 0.0
