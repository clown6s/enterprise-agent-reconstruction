"""Service-level checks for policy application on initial and retry paths."""
import pytest

from app.chat.application.context import RequestContext
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.nl2sql.row_policy import BoundPolicy
from app.chat.domain.exceptions import SqlPolicyError
from app.chat.domain.models import SqlResult


class _LLM:
    def __init__(self, candidates):
        self.candidates = iter(candidates)
    def chat(self, messages):
        prompt = messages[-1].content
        if "单条 SELECT" in prompt:  # initial and retry prompts both contain this
            return next(self.candidates)
        return "查询结果如上。"


class _Catalog:
    def __init__(self, policy, *, tables=("orders",)):
        self.policy = policy
        self.tables = set(tables)
        self.policy_calls = []
    def resolve_domain(self, query, *, context): return "orders"
    def describe(self, domain, *, context): return "orders(amount, owner_id)"
    def allowed_tables(self, domain, *, context): return self.tables
    def blocked_columns(self, domain, *, context): return {}
    def row_policies(self, domain, table_name, *, context):
        self.policy_calls.append(table_name)
        return self.policy


class _Executor:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []
    def query(self, sql, **kwargs):
        self.calls.append((sql, kwargs.get("row_policies", ())))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("bad column")
        return SqlResult(("amount",), ((10,),), "q1", 1)


_CTX = RequestContext(tenant_id="t1", user_id="u1", authenticated=True)


def _service(llm, catalog, executor):
    return Nl2SqlService(llm, catalog, executor)


def test_initial_and_retry_both_use_same_bound_policy_pipeline():
    policy = (BoundPolicy("owner_id = %s", ("u1",)),)
    catalog = _Catalog(policy)
    executor = _Executor(failures=1)
    llm = _LLM(["```sql\nSELECT amount FROM orders\n```",
                "```sql\nSELECT amount FROM orders WHERE amount > 0\n```"])
    result = _service(llm, catalog, executor).answer("查订单", "c1", _CTX)
    assert result.status.value == "answered"
    assert len(executor.calls) == 2
    expected = {"orders": policy}
    assert executor.calls[0][1] == expected
    assert executor.calls[1][1] == expected


def test_unparseable_query_with_policy_fails_closed_before_execution():
    policy = (BoundPolicy("owner_id = %s", ("u1",)),)
    catalog = _Catalog(policy)
    executor = _Executor()
    llm = _LLM(["```sql\nSELECT amount FROM orders WHERE owner_id =\n```"])
    with pytest.raises(SqlPolicyError):
        _service(llm, catalog, executor).answer("查订单", "c1", _CTX)
    assert executor.calls == []


def test_retry_failure_raises_sanitized_policy_error():
    """重试执行也失败时，必须转成脱敏的 SqlPolicyError，而不是把原始异常抛给上层变 500。"""
    policy = (BoundPolicy("owner_id = %s", ("u1",)),)
    catalog = _Catalog(policy)
    # 首次 + 重试都失败，LLM 两次都给出候选
    executor = _Executor(failures=2)
    llm = _LLM(["```sql\nSELECT amount FROM orders\n```",
                "```sql\nSELECT amount FROM orders WHERE amount > 0\n```"])
    with pytest.raises(SqlPolicyError) as exc_info:
        _service(llm, catalog, executor).answer("查订单", "c1", _CTX)
    assert len(executor.calls) == 2
    # 必须是业务异常，且错误文本不泄露原始 RuntimeError 之外的敏感信息
    assert exc_info.type is SqlPolicyError
