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
from .row_policy import BoundPolicy
from .row_rewrite import rewrite_with_row_policies
from .sql_guard import validate_sql
from .tenant_rewrite import physical_tables

_SQL_EXTRACT = re.compile(r"```(?:sql)?\s*(select[\s\S]*?)\s*```", re.I)


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
            allowed_column_loader = getattr(self.catalog, "allowed_columns", None)
            allowed_columns = (allowed_column_loader(domain, context=context)
                               if callable(allowed_column_loader) else {})
            column_loader = getattr(self.catalog, "blocked_columns", None)
            blocked_columns = (column_loader(domain, context=context)
                               if callable(column_loader) else {})
            limits_loader = getattr(self.catalog, "domain_limits", None)
            domain_max_rows, domain_timeout_s = (limits_loader(domain, context=context)
                                                 if callable(limits_loader)
                                                 else (self.max_rows, self.timeout_s))
            max_rows = min(self.max_rows, domain_max_rows)
            timeout_s = domain_timeout_s
        previous_context = ""
        if state is not None and getattr(state, "extra", None):
            previous_question = state.extra.get("last_question")
            if previous_question:
                previous_context = f"上轮已确认的问题（仅用于理解本轮追问）：{previous_question}\n"
        allowed_table_list = ", ".join(sorted(allowed))
        prompt = (
            f"数据库方言：MySQL 8.x。{previous_context}数据域：{domain}\n"
            f"允许使用的真实表名（必须逐字使用，禁止改名、缩写、猜测同义表名）：{allowed_table_list}\n"
            f"{schema}\n"
            "要求：只生成单条 SELECT；只能使用上面列出的确切表名和字段名；"
            "表名、字段名必须以 Schema 原样为准，不得自行改名或补全；必须使用 MySQL 语法；"
            "不得引用 Schema 中不存在的列（例如把‘总额/总金额/合计’直接当成一列 total_amount，"
            "必须用 SUM(amount) AS total_amount 这类聚合表达式计算，聚合别名只可输出，不可作为真实列过滤）；"
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
            sql = validate_sql(sql, allowed_tables=allowed,
                               allowed_columns=allowed_columns,
                               blocked_columns=blocked_columns)
        row_policies = self._row_policies_for(sql, domain, context)
        result = None
        try:
            with self._span("nl2sql.execute_sql"):
                result = self.executor.query(sql, timeout_s=timeout_s,
                                             max_rows=max_rows,
                                             row_policies=row_policies)
        except Exception as exc:
            # 允许基于底层错误重写一次，仍失败才抛出并保留脱敏错误信息。
            retry = self._retry_on_error(query, domain, sql, exc, allowed,
                                         context, blocked_columns=blocked_columns,
                                         allowed_columns=allowed_columns)
            if retry is None:
                raise SqlPolicyError(self._safe_error(exc)) from exc
            rewritten, retry_policies = retry
            try:
                with self._span("nl2sql.execute_sql_retry"):
                    result = self.executor.query(rewritten, timeout_s=timeout_s,
                                                 max_rows=max_rows,
                                                 row_policies=retry_policies)
            except Exception as retry_exc:
                # 重试也失败：同样转成脱敏业务异常，避免底层数据库
                # 异常冒泡成 500 Internal Server Error。
                raise SqlPolicyError(self._safe_error(retry_exc)) from retry_exc
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

    def _row_policies_for(self, sql: str, domain: str, context,
                          ) -> dict[str, tuple[BoundPolicy, ...]]:
        """为每张物理表合并认证租户条件和行级权限策略。"""
        tables = physical_tables(sql)
        tenant_id = context.tenant_id
        if not tenant_id:
            raise SqlPolicyError("缺少认证租户，拒绝执行查询")
        loader = getattr(self.catalog, "row_policies", None)
        policies_by_table: dict[str, tuple[BoundPolicy, ...]] = {}
        for table in tables:
            resolved = (loader(domain, table, context=context)
                        if callable(loader) else ())
            policies = [BoundPolicy("tenant_id = %s", (tenant_id,))]
            policies.extend(resolved or ())
            policies_by_table[table.lower()] = tuple(policies)
        if not policies_by_table:
            raise SqlPolicyError("查询未引用物理表，拒绝执行")
        # 在此预校验可改写性，确保执行器收到的安全策略能够应用。
        rewrite_with_row_policies(sql, policies_by_table)
        return policies_by_table

    def _retry_on_error(self, query: str, domain: str, sql: str, error: Exception,
                        allowed_tables: set[str], context,
                        blocked_columns: dict | None = None,
                        allowed_columns: dict | None = None) -> tuple[str, tuple] | None:
        """针对可修复的 SQL 执行错误，请模型最多重写一次（复用同一安全 pipeline）。"""
        prompt = (
            "上一条 MySQL SELECT 执行失败。只返回修正后的单条 SELECT 代码块，"
            "只能使用原 SQL 的允许表字段，必须保留 tenant_id 过滤；不要解释。\n"
            f"数据域：{domain}\n原问题：{query}\n原 SQL：{sql}\n"
            f"数据库错误类型：{type(error).__name__}\n"
            f"数据库错误信息：{self._safe_error(error)}\n"
        )
        try:
            raw = self.llm.chat([ChatMessage("user", prompt)])
            candidate = self._extract_sql(raw)
            if not candidate:
                return None
            candidate = validate_sql(candidate, allowed_tables=allowed_tables,
                                    allowed_columns=allowed_columns,
                                    blocked_columns=blocked_columns)
            policies = self._row_policies_for(candidate, domain, context)
            return candidate, policies
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
