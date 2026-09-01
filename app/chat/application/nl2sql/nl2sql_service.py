"""NL2SQL: candidate generation -> guard -> read-only execution -> explanation."""
import json
import re

from ...domain.exceptions import LlmError, SqlGenerationError, SqlPolicyError
from ...domain.models import ChatMessage, ChatResult, ChatStatus, Intent
from ...security.context_boundary import SYSTEM_POLICY
from ..context import RequestContext
from ..ports import LLM, ReadonlySqlExecutor, SchemaCatalog
from .sql_guard import validate_sql

_SQL_EXTRACT = re.compile(r"```(?:sql)?\s*(select[\s\S]*?)\s*```", re.I)


class Nl2SqlService:
    def __init__(self, llm: LLM, catalog: SchemaCatalog,
                 executor: ReadonlySqlExecutor, *, timeout_s: float = 10.0,
                 max_rows: int = 1000):
        self.llm = llm
        self.catalog = catalog
        self.executor = executor
        self.timeout_s = timeout_s
        self.max_rows = max_rows

    def answer(self, query: str, conversation_id: str,
               context: RequestContext | None = None,
               state=None) -> ChatResult:
        context = context or RequestContext()
        domain = (getattr(state, "last_domain", None)
                  if (state is not None and self.catalog.describe(
                      state.last_domain, context=context)) else None)
        if domain is None:
            domain = self.catalog.resolve_domain(query, context=context)
        if domain is None:
            return ChatResult(
                answer="无法确定要查询的数据域，请说明是订单、采购还是其他业务数据。",
                status=ChatStatus.CLARIFICATION, mode=Intent.NL2SQL,
                conversation_id=conversation_id, warnings=("domain_unknown",),
                trace_id=context.trace_id,
            )
        schema = self.catalog.describe(domain, context=context)
        allowed = self.catalog.allowed_tables(domain, context=context)
        prompt = (
            f"数据域：{domain}\n{schema}\n"
            "要求：只生成单条 SELECT；只能使用上述表和字段；必须给出时间或过滤条件；"
            "返回格式：```sql\nSELECT ...\n```\n"
            f"问题：{query}"
        )
        messages = [ChatMessage("system", SYSTEM_POLICY), ChatMessage("user", prompt)]
        try:
            raw = self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 生成 SQL 失败: {type(exc).__name__}") from exc
        sql = self._extract_sql(raw)
        if not sql:
            raise SqlGenerationError("LLM 未返回合法 SQL")
        sql = validate_sql(sql, allowed_tables=allowed)
        try:
            result = self.executor.query(sql, timeout_s=self.timeout_s,
                                         max_rows=self.max_rows)
        except Exception as exc:
            raise SqlPolicyError(f"只读查询失败: {type(exc).__name__}") from exc
        explanation = self._explain(query, domain, result)
        return ChatResult(
            answer=explanation, status=ChatStatus.ANSWERED, mode=Intent.NL2SQL,
            conversation_id=conversation_id,
            sql={"query": sql, "query_id": result.query_id,
                 "domain": domain, "columns": list(result.columns),
                 "row_count": result.row_count},
            trace_id=context.trace_id,
        )

    def _extract_sql(self, raw: str) -> str | None:
        match = _SQL_EXTRACT.search(raw)
        if match:
            return match.group(1).strip()
        candidate = raw.strip()
        if candidate.lower().startswith("select"):
            return candidate
        return None

    def _explain(self, query: str, domain: str, result) -> str:
        if result.row_count == 0:
            return f"查询执行成功，但没有符合条件的数据。"
        preview = [dict(zip(result.columns, row)) for row in result.rows[:5]]
        messages = [
            ChatMessage("system", SYSTEM_POLICY),
            ChatMessage("user",
                        f"原问题：{query}\n数据域：{domain}\n查询结果：\n"
                        f"{json.dumps(preview, ensure_ascii=False)}\n"
                        f"共 {result.row_count} 行。请用中文简洁解释结果，只依据给定数据。"),
        ]
        try:
            return self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 解释结果失败: {type(exc).__name__}") from exc
