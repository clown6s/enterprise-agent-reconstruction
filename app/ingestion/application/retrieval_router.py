"""查询意图到检索策略的路由。"""


class DefaultRetrievalRouter:
    """保持现有 API 语义：未指定时使用 dense，显式 hybrid 才使用 hybrid。"""

    def route(self, profile, requested_mode: str) -> str:
        if requested_mode not in {"dense", "hybrid"}:
            raise ValueError(f"不支持的检索模式: {requested_mode}")
        return requested_mode
