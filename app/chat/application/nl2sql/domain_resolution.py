"""数据域解析的共享纯函数。

Memory 与 MySQL 两个 catalog 使用同一套打分与消歧规则，避免测试环境和
生产环境行为分叉：关键词累计得分，只有唯一高分或与第二名分差足够大才返回，
否则返回 None 表示“域未知或歧义”，由调用方决定澄清。
"""

from typing import Iterable, Mapping


def resolve_domain(
    query: str,
    domain_keywords: Mapping[str, Iterable[tuple[str, float]]],
    *,
    margin: float = 1.3,
) -> str | None:
    """按关键词得分挑选唯一数据域；无命中或歧义返回 None。

    ``domain_keywords`` 形如 ``{"orders": [("订单", 1.0), ("销售", 1.0)]}``。
    长关键词按长度加成，与 MySQL 实现保持一致；歧义判定用第二名×margin 比较。
    """
    if not query:
        return None
    scores: dict[str, float] = {}
    for domain, keywords in domain_keywords.items():
        for keyword, weight in keywords:
            if keyword and keyword in query:
                bonus = 1.0 + min(len(keyword), 8) * 0.1
                scores[domain] = scores.get(domain, 0.0) + float(weight) * bonus
    if not scores:
        return None
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ordered[0]
    if len(ordered) == 1 or ordered[1][1] * margin < top_score:
        return top
    return None  # 多个域都命中且分差小，需要澄清
