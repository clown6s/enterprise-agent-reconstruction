"""通用知识/技术问答执行器。

企业知识问答仍走 RAG（必须有企业文档支撑）；当问题命中通用/技术概念特征、
且企业检索没有可支撑片段时，用注入的 LLM 直接回答，避免把通用问题伪装成
业务澄清或返回生硬的“无内容”。本执行器不调用工具、不触库，也不声明引用。
"""
import re

from ..domain.models import ChatMessage, ChatResult, ChatStatus, Intent
from .context import RequestContext
from .ports import LLM

# 通用/技术概念特征。命中且企业检索无召回时才启用 LLM 兜底，
# 避免让模型凭空作答企业制度类问题。
_GENERAL_TECHNICAL_RE = re.compile(
    r"向量|嵌入|表示|上下文|模型|算法|机制|原理|检索|索引|倒排|BM25|RRF|"
    r"重排序|跨编码器|同义词|TF-IDF|注意力|Transformer|神经网络|"
    r"数学|定义|数据结构|一致性|工程|架构|调试|排查"
)


def is_general_technical(query: str) -> bool:
    """判断问题是否属于通用/技术概念（非企业业务制度）。"""
    return bool(query) and bool(_GENERAL_TECHNICAL_RE.search(query))


class GeneralQaAnswerer:
    """无企业文档支撑时的通用知识回答通道。"""

    def __init__(self, llm: LLM):
        self._llm = llm

    def answer(self, query: str, conversation_id: str,
               context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        prompt = (
            "你是通用知识问答助手。请准确、完整地直接回答下面的技术/概念问题，"
            "不要编造来源，不要使用‘根据参考资料’之类的开头，回答以结论和解释开始。\n"
            f"问题：{query}"
        )
        try:
            raw = self._llm.chat([ChatMessage("user", prompt)]).strip()
        except Exception:
            raw = ""
        if not raw:
            return ChatResult(
                answer="当前问题不属于企业业务数据查询，且企业知识库没有相关文档，暂时无法回答。",
                status=ChatStatus.NO_CONTEXT, mode=Intent.KNOWLEDGE_QA,
                conversation_id=conversation_id,
                warnings=("general_no_answer",), trace_id=context.trace_id,
            )
        return ChatResult(
            answer=raw, status=ChatStatus.ANSWERED, mode=Intent.KNOWLEDGE_QA,
            conversation_id=conversation_id, warnings=("general_knowledge",),
            trace_id=context.trace_id,
        )

    def close(self) -> None:
        pass
