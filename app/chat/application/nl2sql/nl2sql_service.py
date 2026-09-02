"""NL2SQL: candidate generation -> guard -> read-only execution -> explanation.

安全与方言约束：
- LLM 只生成 MySQL 8.x 语法。
- 程序强制注入 tenant_id 过滤，不信任模型自己加的租户条件。
- 执行失败时给 LLM 一次基于错误的重写机会，仍失败才抛出。
"""
import json
import re
from contextlib import nullcontext
from datetime import date, datetime

from ...domain.exceptions import LlmError, SqlGenerationError, SqlPolicyError
from ...domain.models import ChatMessage, ChatResult, ChatStatus, Intent
from ...security.context_boundary import SYSTEM_POLICY
from ..context import RequestContext
from ..ports import LLM, ReadonlySqlExecutor, SchemaCatalog
from .sql_guard import validate_sql

_SQL_EXTRACT = re.compile(r"```(?:sql)?\s*(select[\s\S]*?)\s*```", re.I)
# 在这些关键字之前插入 tenant 条件，避免追加到 GROUP/ORDER/LIMIT 之后。
_CLAUSE_BOUNDARY = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|FOR\s+UPDATE)\b", re.I)
_TENANT_FILTER = re.compile(
    r"\btenant_id\s*=\s*(?:'[^']*'|\"[^\"]*\"|[A-Za-z0-9_.:-]+)", re.I)


class Nl2SqlService:
    def _span(self, name: str, **attributes):
        return self.trace_provider.span(name, **attributes) if self.trace_provider else nullcontext()

    def __init__(self, llm: LLM, catalog: SchemaCatalog,
                 executor: ReadonlySqlExecutor, *, timeout_s: float = 10.0,
                 max_rows: int = 1000, trace_provider=None):
        self.llm = llm
        self.catalog = catalog
        self.executor = executor
        self.timeout_s = timeout_s
        self.max_rows = max_rows
        self.trace_provider = trace_provider

    def answer(self, query: str, conversation_id: str,
               context: RequestContext | None = None,
               state=None) -> ChatResult:
        context = context or RequestContext()
        with self._span("nl2sql.resolve_domain"):
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
        with self._span("nl2sql.load_schema"):
            schema = self.catalog.describe(domain, context=context)
            allowed = self.catalog.allowed_tables(domain, context=context)
        previous_context = ""
        if state is not None and getattr(state, "extra", None):
            previous_question = state.extra.get("last_question")
            if previous_question:
                previous_context = f"上轮已确认的问题（仅用于理解本轮追问）：{previous_question}\n"
        prompt = (
            f"数据库方言：MySQL 8.x。{previous_context}数据域：{domain}\n{schema}\n"
            "要求：只生成单条 SELECT；只能使用上述表和字段；必须使用 MySQL 语法；"
            "日期请使用 DATE_FORMAT、DATE_ADD、DATE_SUB 和 INTERVAL 1 MONTH，禁止 DATE_TRUNC 和 PostgreSQL 字符串 interval；"
            "必须包含 tenant_id 过滤条件；只返回 SQL 代码块，不要解释。\n"
            "返回格式：```sql\nSELECT ...\n```\n"
            f"问题：{query}"
        )
        messages = [ChatMessage("system", SYSTEM_POLICY), ChatMessage("user", prompt)]
        try:
            with self._span("nl2sql.llm_generate"):
                raw = self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 生成 SQL 失败: {type(exc).__name__}") from exc
        sql = self._extract_sql(raw)
        if not sql:
            raise SqlGenerationError("LLM 未返回合法 SQL")
        with self._span("nl2sql.validate_sql"):
            sql = validate_sql(sql, allowed_tables=allowed)
        sql = self._enforce_tenant(sql, context.tenant_id)
        result = None
        try:
            with self._span("nl2sql.execute_sql"):
                result = self.executor.query(sql, timeout_s=self.timeout_s,
                                             max_rows=self.max_rows)
        except Exception as exc:
            # 允许基于底层错误重写一次，仍失败才抛出并保留脱敏错误信息。
            rewritten = self._retry_on_error(query, domain, sql, exc, allowed, context.tenant_id)
            if rewritten is None:
                raise SqlPolicyError(self._safe_error(exc)) from exc
            with self._span("nl2sql.execute_sql_retry"):
                result = self.executor.query(rewritten, timeout_s=self.timeout_s,
                                             max_rows=self.max_rows)
            sql = rewritten
        explanation = self._explain(query, domain, result)
        return ChatResult(
            answer=explanation, status=ChatStatus.ANSWERED, mode=Intent.NL2SQL,
            conversation_id=conversation_id,
            sql={"query": sql, "query_id": result.query_id,
                 "domain": domain, "columns": list(result.columns),
                 "row_count": result.row_count},
            trace_id=context.trace_id,
        )

    @staticmethod
    def _enforce_tenant(sql: str, tenant_id: str) -> str:
        """覆盖模型租户条件，只使用认证上下文中的 tenant_id。"""
        if not tenant_id:
            raise SqlPolicyError("缺少认证租户，拒绝执行查询")
        escaped = tenant_id.replace("'", "''")
        predicate = f"tenant_id = '{escaped}'"
        # 直接替换模型生成的租户谓词，避免留下 WHERE AND 等残片。
        if _TENANT_FILTER.search(sql):
            return _TENANT_FILTER.sub(predicate, sql, count=1)
        boundary = _CLAUSE_BOUNDARY.search(sql)
        prefix, suffix = (sql[:boundary.start()], sql[boundary.start():]) if boundary else (sql, "")
        if re.search(r"\bWHERE\b", prefix, re.I):
            return f"{prefix} AND {predicate} {suffix}".strip()
        return f"{prefix} WHERE {predicate} {suffix}".strip()

    def _retry_on_error(self, query: str, domain: str, sql: str, error: Exception,
                        allowed_tables: set[str], tenant_id: str) -> str | None:
        """针对可修复的 SQL 执行错误，请模型最多重写一次。"""
        prompt = (
            "上一条 MySQL SELECT 执行失败。只返回修正后的单条 SELECT 代码块，"
            "只能使用原 SQL 的允许表字段，必须保留 tenant_id 过滤；不要解释。\n"
            f"数据域：{domain}\n原问题：{query}\n原 SQL：{sql}\n"
            f"数据库错误类型：{type(error).__name__}\n"
        )
        try:
            raw = self.llm.chat([ChatMessage("user", prompt)])
            candidate = self._extract_sql(raw)
            if not candidate:
                return None
            candidate = validate_sql(candidate, allowed_tables=allowed_tables)
            return self._enforce_tenant(candidate, tenant_id)
        except Exception:
            return None

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """保留可排查错误类型和短消息，不返回连接凭据。"""
        text = str(error).replace("password", "[redacted]").replace("PASSWORD", "[redacted]")
        return f"只读查询失败: {type(error).__name__}: {text[:240]}"

    @staticmethod
    def _jsonable(value):
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

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
        preview = [{key: self._jsonable(value) for key, value in
                    zip(result.columns, row)} for row in result.rows[:5]]
        messages = [
            ChatMessage("system", SYSTEM_POLICY),
            ChatMessage("user",
                        f"原问题：{query}\n数据域：{domain}\n查询结果：\n"
                        f"{json.dumps(preview, ensure_ascii=False)}\n"
                        f"共 {result.row_count} 行。请用中文简洁解释结果，只依据给定数据。"),
        ]
        try:
            with self._span("nl2sql.llm_explain"):
                return self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 解释结果失败: {type(exc).__name__}") from exc
