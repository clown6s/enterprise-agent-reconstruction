"""文档结构分析协议与默认适配器。"""
from collections.abc import Iterable

from ..domain.models import ContentBlock


class StructureAnalyzer:
    """把解析内容块转换为带结构标记的内容块。"""

    def analyze(self, blocks: Iterable[ContentBlock]) -> tuple[ContentBlock, ...]:
        return tuple(blocks)


class IdentityStructureAnalyzer(StructureAnalyzer):
    """默认适配器：保留解析器已经确定的结构事实。"""

