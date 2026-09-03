"""NL2SQL：候选生成 → 守卫校验 → 只读执行 → 结果解释。

安全与方言约束：
- LLM 只生成 MySQL 8.x 语法。
- 程序强制注入 tenant_id 过滤，不信任模型自己加的租户条件。
- 执行失败时给 LLM 一次基于错误的重写机会，仍失败才抛出。
"""
import json
import re
from contextlib import nullcontext
from datetime import date, datetime

import structlog

from ...domain.exceptions import LlmError, SqlGenerationError, SqlPolicyError
from ...domain.models import ChatMessage, ChatResult, ChatStatus, Intent
from ...security.context_boundary import SYSTEM_POLICY, find_injection
from ..context import RequestContext
from ..ports import LLM, ReadonlySqlExecutor, SchemaCatalog
from .row_policy import BoundPolicy
from .row_rewrite import rewrite_with_row_policies
from .sql_guard import validate_sql
from .tenant_rewrite import physical_tables


logger = structlog.get_logger(__name__)


_SQL_EXTRACT = re.compile(r"```(?:sql|mysql)?\s*(select[\s\S]*?)\s*```", re.I)
# schema 提示文本的整行上限：域很大时避免整段塞给 LLM 浪费 token。
_MAX_SCHEMA_PROMPT_LINES = 120
_ERROR_URL = re.compile(r"\b[a-z][\w+.-]*://\S+", re.I)
_ERROR_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_ERROR_CREDENTIAL = re.compile(r"'[^']*@[^']*'|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_ERROR_SENSITIVE_FIELD = re.compile(
    r"\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b"
    r"\s*[=:]\s*[^,;\s]+", re.I)


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
        # 先做提示注入检测：命中即拒绝，避免不可信的用户内容进入生成链路，
        # 也防止其引导模型改写 SQL 绕过守卫（sql_guard 无法看见该改写）。
        injected = find_injection(query)
        if injected:
            logger.warning("nl2sql_injection_blocked", markers=injected,
                           trace_id=context.trace_id)
            raise SqlPolicyError("检测到可疑内容，已拒绝执行")
        # 行级权限强制要求 tenant_id，匿名请求无法安全执行。
        # 在此提前返回友好提示，避免后续在 _row_policies_for 抛异常变成 500。
        if not context.tenant_id:
            return ChatResult(
                answer="查询业务数据需要登录。请先完成认证后再提问。",
                status=ChatStatus.CLARIFICATION, mode=Intent.NL2SQL,
                conversation_id=conversation_id, warnings=("auth_required",),
                trace_id=context.trace_id,
            )
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
            allowed_columns = self.catalog.allowed_columns(domain, context=context)
            blocked_columns = self.catalog.blocked_columns(domain, context=context)
            domain_max_rows, domain_timeout_s = self.catalog.domain_limits(
                domain, context=context)
            max_rows = min(self.max_rows, domain_max_rows)
            # 超时同样钳制到服务层上限，避免某数据域配了过大的值绕过默认限制。
            timeout_s = min(self.timeout_s, domain_timeout_s)
        previous_context = ""
        if state is not None and getattr(state, "extra", None):
            previous_question = state.extra.get("last_question")
            if previous_question:
                previous_context = f"上轮已确认的问题（仅用于理解本轮追问）：{previous_question}\n"
        allowed_table_list = ", ".join(sorted(allowed))
        # 按行截断 schema 提示文本：域很大时避免整段塞给 LLM 浪费 token，
        # 允许表名已在上方显式列出，截断不会影响表名约束。
        schema_lines = schema.splitlines()
        if len(schema_lines) > _MAX_SCHEMA_PROMPT_LINES:
            schema = "\n".join(schema_lines[:_MAX_SCHEMA_PROMPT_LINES]) + "\n…（schema 过长已截断）"
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
        retried = False
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
                retried = True
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
                 "row_count": result.row_count, "truncated": result.truncated,
                 # 如实携带执行状态，供审计记录真实链路（重试仍成功）。
                 "generation_status": "executed", "guard_status": "allowed",
                 "execution_status": "success", "execution_retried": retried},
            trace_id=context.trace_id,
        )

    def _row_policies_for(self, sql: str, domain: str, context,
                          ) -> dict[str, tuple[BoundPolicy, ...]]:
        """为每张物理表合并认证租户条件和行级权限策略。"""
        tables = physical_tables(sql)
        tenant_id = context.tenant_id
        if not tenant_id:
            raise SqlPolicyError("缺少认证租户，拒绝执行查询")
        policies_by_table: dict[str, tuple[BoundPolicy, ...]] = {}
        for table in tables:
            resolved = self.catalog.row_policies(domain, table, context=context) or ()
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
                        allowed_columns: dict | None = None
                        ) -> tuple[str, dict[str, tuple[BoundPolicy, ...]]] | None:
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
        # 重试链路的任意异常都应回退到首次错误，避免覆盖原始诊断。
        # 记录失败原因，便于区分"模型未重写"还是"重写后被守卫/策略拦截"。
        except Exception as exc:  # noqa: BLE001
            logger.warning("nl2sql_retry_failed", original_error=type(error).__name__,
                           retry_error=type(exc).__name__)
            return None

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """保留错误类型和诊断结构，同时移除连接凭据及网络地址。"""
        text = str(error)
        text = _ERROR_SENSITIVE_FIELD.sub("[敏感字段]=[已脱敏]", text)
        text = _ERROR_CREDENTIAL.sub("'[凭据已脱敏]'", text)
        text = _ERROR_URL.sub("[地址已脱敏]", text)
        text = _ERROR_IP.sub("[地址已脱敏]", text)
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
        # 结果被截断时如实提示，避免把"已返回的前 N 行"误报为全部行数。
        count_note = (
            f"结果超过 {result.row_count} 行，以下仅为前 {result.row_count} 行。"
            if result.truncated else f"共 {result.row_count} 行。"
        )
        messages = [
            ChatMessage("system", SYSTEM_POLICY),
            ChatMessage("user",
                        f"原问题：{query}\n数据域：{domain}\n查询结果：\n"
                        f"{json.dumps(preview, ensure_ascii=False)}\n"
                        f"{count_note} 请用中文简洁解释结果，只依据给定数据。"),
        ]
        try:
            with self._span("nl2sql.llm_explain"):
                return self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 解释结果失败: {type(exc).__name__}") from exc
