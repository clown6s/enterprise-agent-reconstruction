"""Unit tests for the row-level policy DSL and its binding rules."""
import pytest

from app.chat.application.nl2sql.row_policy import (
    bind_policy, compile_template, validate_policy_columns,
)
from app.chat.domain.exceptions import SqlPolicyError, ValidationError


# --- 模板校验（失败即关闭）---

def test_accepts_tenant_and_user_scalars():
    p = bind_policy("tenant_id = :tenant_id AND owner_id = :user_id",
                    tenant_id="t1", user_id="u1")
    assert p.sql == "tenant_id = %s AND owner_id = %s"
    assert p.params == ("t1", "u1")


def test_accepts_list_placeholders():
    p = bind_policy("department_id IN :department_ids",
                    department_ids=("d1", "d2"))
    assert p.sql == "department_id IN (%s, %s)"
    assert p.params == ("d1", "d2")


def test_empty_list_expands_to_null_deny():
    p = bind_policy("department_id IN :department_ids")
    assert p.sql == "department_id IN (NULL)"
    assert p.params == ()


def test_empty_role_list_expands_to_null():
    p = bind_policy("region IN :role_names", role_names=())
    assert "(NULL)" in p.sql


def test_unknown_placeholder_rejected():
    with pytest.raises(SqlPolicyError):
        bind_policy("owner_id = :owner_id", user_id="u1")


def test_percent_rejected():
    with pytest.raises(SqlPolicyError):
        bind_policy("note LIKE '%x%'", user_id="u1")


def test_write_keyword_rejected():
    with pytest.raises(SqlPolicyError):
        bind_policy("id IN (SELECT id FROM secrets)", user_id="u1")


def test_semicolon_and_comment_rejected():
    with pytest.raises(SqlPolicyError):
        bind_policy("owner_id = :user_id; DROP TABLE orders", user_id="u1")
    with pytest.raises(SqlPolicyError):
        bind_policy("owner_id = :user_id -- nope", user_id="u1")


def test_blank_template_rejected():
    with pytest.raises(SqlPolicyError):
        compile_template("   ")


def test_missing_scalar_value_fails_closed():
    with pytest.raises(SqlPolicyError):
        bind_policy("owner_id = :user_id", tenant_id="t1")


def test_policy_columns_rejects_unknown_column():
    with pytest.raises(ValidationError):
        validate_policy_columns("owner_id = :user_id", {"tenant_id": True})


def test_policy_columns_rejects_sensitive_column():
    with pytest.raises(ValidationError):
        validate_policy_columns(
            "secret_salary = :user_id", {"secret_salary": True},
            sensitive={"secret_salary"})


def test_policy_columns_rejects_non_filterable_column():
    with pytest.raises(ValidationError):
        validate_policy_columns("amount = :user_id", {"amount": False})


def test_policy_columns_allows_registered_filterable_column():
    cols = validate_policy_columns(
        "department_id IN :department_ids", {"department_id": True})
    assert cols == {"department_id"}


def test_policy_columns_excludes_placeholders_and_keywords():
    cols = validate_policy_columns(
        "owner_id = :user_id AND region = :role_names", {"owner_id": True, "region": True})
    assert cols == {"owner_id", "region"}


def test_double_colon_cast_does_not_create_placeholder_token():
    # ``::int``（一次类型转换）绝不能被视为裸 ``:int`` 占位符；
    # 负向零宽断言可防止它变成未授权的标记。
    p = bind_policy("amount::int = :tenant_id", tenant_id="t1")
    assert p.sql == "amount::int = %s"
    assert p.params == ("t1",)
