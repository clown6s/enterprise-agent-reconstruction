"""RAG execution: retrieve -> bounded context -> LLM -> citations."""
import json
import re

from ..domain.models import (ChatMessage, ChatResult, ChatStatus, Citation,
                             CitationAudit, Intent)
from ..domain.exceptions import LlmError
from ..security.context_boundary import (build_messages, referenced_citations,
                                         sanitize_answer)
from .context import RequestContext
from .context_builder import ContextBuilder
from .ports import DocumentRetriever, LLM


class RagAnswerer:
    def __init__(self, retriever: DocumentRetriever, llm: LLM,
                 context_builder: ContextBuilder | None = None):
        self.retriever = retriever
        self.llm = llm
        self.context_builder = context_builder or ContextBuilder()

    def answer(self, query: str, conversation_id: str,
               history: list[ChatMessage] | None = None,
               context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        items = self.retriever.retrieve(query, top_k=self.context_builder.max_chunks)
        context_text, citations = self.context_builder.build(items)
        if not citations:
            return ChatResult(
                answer="参考资料中没有相关内容，无法回答。",
                status=ChatStatus.NO_CONTEXT, mode=Intent.KNOWLEDGE_QA,
                conversation_id=conversation_id,
                warnings=("no_context",),
                trace_id=context.trace_id,
            )
        prompt = ("只能依据用户问题和参考片段中明确出现或直接推导的事实回答，禁止编造。\n"
                  "资料不足时 answer 必须写‘根据当前资料无法确定。’且 grounded=false。\n"
                  "只返回 JSON 对象，字段为 answer(string)、used_citations(整数数组)、grounded(boolean)。\n"
                  "answer 不得包含 [n] 引用编号；used_citations 只能填实际使用的片段编号。\n"
                  + context_text)
        messages = build_messages(history or [], query, prompt)
        try:
            raw = self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 回答失败: {type(exc).__name__}") from exc
        answer, used, grounded, parse_warnings = self._parse_response(raw, len(citations))
        selected = tuple(citations[index - 1] for index in used)
        audit = CitationAudit(sent=tuple(range(1, len(citations) + 1)),
                              used=tuple(used),
                              unused=tuple(i for i in range(1, len(citations) + 1) if i not in used),
                              grounded=grounded and bool(used))
        return ChatResult(
            answer=answer, status=ChatStatus.ANSWERED, mode=Intent.KNOWLEDGE_QA,
            conversation_id=conversation_id, citations=selected,
            warnings=parse_warnings, trace_id=context.trace_id,
            citation_audit=audit,
        )

    @staticmethod
    def _parse_response(raw: str, count: int):
        warnings = []
        data = None
        try:
            candidate = raw.strip()
            if candidate.startswith("```"):
                candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
            data = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            # Legacy providers may return prose with [n]; accept only valid markers.
            used = []
            for value in re.findall(r"\[(\d+)\]", raw or ""):
                index = int(value)
                if 1 <= index <= count and index not in used:
                    used.append(index)
            answer = re.sub(r"\[\d+\]", "", raw or "").strip()
            warnings.append("llm_response_not_structured")
            return answer, used, bool(used), tuple(warnings)
        answer = data.get("answer") if isinstance(data, dict) else None
        raw_used = data.get("used_citations") if isinstance(data, dict) else None
        grounded = data.get("grounded") if isinstance(data, dict) else False
        if not isinstance(answer, str):
            answer = "根据当前资料无法确定。"
            warnings.append("invalid_answer")
        if not isinstance(raw_used, list):
            raw_used = []
            warnings.append("invalid_used_citations")
        used = []
        for item in raw_used:
            if isinstance(item, int) and not isinstance(item, bool) and 1 <= item <= count and item not in used:
                used.append(item)
            else:
                warnings.append("invalid_citation_number")
        if re.search(r"\[\d+\]", answer):
            answer = re.sub(r"\[\d+\]", "", answer).strip()
            warnings.append("citation_markers_removed")
        grounded = bool(grounded) and bool(used)
        if not grounded and answer != "根据当前资料无法确定。":
            warnings.append("answer_not_grounded")
        return answer, used, grounded, tuple(dict.fromkeys(warnings))
