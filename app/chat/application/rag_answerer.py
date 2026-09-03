"""RAG execution: retrieve -> bounded context -> LLM -> citations."""
import json
import re
from contextlib import nullcontext

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
                 context_builder: ContextBuilder | None = None,
                 trace_provider=None):
        self.retriever = retriever
        self.llm = llm
        self.context_builder = context_builder or ContextBuilder()
        self.trace_provider = trace_provider

    def answer(self, query: str, conversation_id: str,
               history: list[ChatMessage] | None = None,
               context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        retrieval_span = (self.trace_provider.span(
            "rag.retrieve", top_k=self.context_builder.max_chunks)
            if self.trace_provider else nullcontext())
        with retrieval_span:
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
        prompt = ("请优先依据下面的参考片段回答用户问题，不要调用外部知识补充事实。\n"
                  "如果片段能直接或部分支持答案，请正常回答；不确定的部分要明确说明。\n"
                  "回答要围绕当前问题完整展开，充分利用所有相关片段，不要只给一句过度概括的答案。\n"
                  "answer 直接从结论和解释开始，禁止出现‘根据参考资料’、‘根据提供的参考资料’等来源前缀。\n"
                  "只有参考片段完全没有相关信息时，才回答‘根据当前资料无法确定。’\n"
                  "只返回 JSON 对象，字段为 answer(string)、used_citations(整数数组)、grounded(boolean)。\n"
                  "answer 不得包含 [n] 引用编号；used_citations 是审计字段，填写实际参考的片段编号。\n"
                  + context_text)
        messages = build_messages(history or [], query, prompt)
        llm_span = (self.trace_provider.span("rag.llm_generate")
                    if self.trace_provider else nullcontext())
        try:
            with llm_span:
                raw = self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 回答失败: {type(exc).__name__}") from exc
        answer, used, grounded, parse_warnings = self._parse_response(raw, len(citations))
        selected = tuple(citations[index - 1] for index in used)
        sent_numbers = tuple(range(1, len(citations) + 1))
        unused_numbers = tuple(i for i in sent_numbers if i not in used)
        sent_details = tuple(self._citation_detail(i, item)
                             for i, item in enumerate(items[:len(citations)], 1))
        detail_by_no = {detail["no"]: detail for detail in sent_details}
        audit = CitationAudit(
            sent=sent_numbers, used=tuple(used), unused=unused_numbers,
            grounded=grounded and bool(used), sent_details=sent_details,
            used_details=tuple(detail_by_no[i] for i in used),
            unused_details=tuple(detail_by_no[i] for i in unused_numbers),
        )
        return ChatResult(
            answer=answer, status=ChatStatus.ANSWERED, mode=Intent.KNOWLEDGE_QA,
            conversation_id=conversation_id, citations=selected,
            warnings=parse_warnings, trace_id=context.trace_id,
            citation_audit=audit,
        )

    @staticmethod
    def _clean_answer_prefix(answer: str) -> str:
        """删除不应展示给用户的来源声明前缀。"""
        prefixes = (
            "根据参考资料，", "根据参考资料:", "根据提供的参考资料，",
            "根据提供的参考资料:", "根据检索结果，", "根据检索结果:",
        )
        for prefix in prefixes:
            if answer.startswith(prefix):
                return answer[len(prefix):].lstrip()
        return answer

    @staticmethod
    def _citation_detail(number, item):
        """把编号映射到真实召回来源，禁止信任模型生成的来源字段。"""
        return {
            "no": number,
            "document_id": item.document_id,
            "chunk_id": item.chunk_id,
            "page": item.page,
            "score": item.score,
        }

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
            # 旧版 provider 可能返回带 [n] 的文本；仅接受合法的标记。
            used = []
            for value in re.findall(r"\[(\d+)\]", raw or ""):
                index = int(value)
                if 1 <= index <= count and index not in used:
                    used.append(index)
            answer = re.sub(r"\[\d+\]", "", raw or "").strip()
            answer = RagAnswerer._clean_answer_prefix(answer)
            warnings.append("llm_response_not_structured")
            return answer, used, bool(used), tuple(warnings)
        answer = data.get("answer") if isinstance(data, dict) else None
        raw_used = data.get("used_citations") if isinstance(data, dict) else None
        grounded = data.get("grounded") if isinstance(data, dict) else False
        if not isinstance(answer, str):
            answer = "根据当前资料无法确定。"
            warnings.append("invalid_answer")
        else:
            answer = RagAnswerer._clean_answer_prefix(answer)
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
