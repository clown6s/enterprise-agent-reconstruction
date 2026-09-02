"""AST row-policy rewrite coverage for complex read-only query shapes."""
import pytest

from app.chat.application.nl2sql.row_policy import BoundPolicy
from app.chat.application.nl2sql.row_rewrite import rewrite_with_row_policies
from app.chat.domain.exceptions import SqlPolicyError


def policy(sql, *params):
    return (BoundPolicy(sql, params),)


def test_join_rewrites_each_physical_table_and_preserves_aliases():
    sql, params = rewrite_with_row_policies(
        "SELECT o.amount, c.name FROM orders o JOIN customers c "
        "ON c.id = o.customer_id",
        {
            "orders": policy("owner_id = %s", "user-1"),
            "customers": policy("tenant_id = %s", "tenant-1"),
        },
    )
    assert "AS o" in sql and "AS c" in sql
    assert "FROM (SELECT * FROM orders" in sql
    assert "JOIN (SELECT * FROM customers" in sql
    assert params == ("user-1", "tenant-1")
    assert "user-1" not in sql and "tenant-1" not in sql


def test_cte_and_nested_subquery_rewrite_physical_tables():
    sql, params = rewrite_with_row_policies(
        "WITH recent AS (SELECT amount FROM orders) "
        "SELECT x.amount FROM (SELECT amount FROM recent) x",
        {"orders": policy("department_id IN (%s, %s)", "d1", "d2")},
    )
    assert "FROM (SELECT * FROM orders" in sql
    assert "AS orders" in sql
    assert params == ("d1", "d2")


def test_union_rewrites_each_occurrence_in_union_branches():
    sql, params = rewrite_with_row_policies(
        "SELECT amount FROM orders UNION ALL SELECT amount FROM line_items",
        {"orders": policy("owner_id = %s", "u1"),
         "line_items": policy("owner_id = %s", "u2")},
    )
    assert sql.count("SELECT * FROM orders") == 1
    assert sql.count("SELECT * FROM line_items") == 1
    assert params == ("u1", "u2")


def test_no_policy_keeps_legacy_sql_and_params():
    original = "SELECT amount FROM orders ORDER BY amount"
    assert rewrite_with_row_policies(original, {}) == (original, ())


def test_empty_list_deny_stays_parameter_free():
    sql, params = rewrite_with_row_policies(
        "SELECT amount FROM orders",
        {"orders": policy("department_id IN (NULL)")},
    )
    assert "department_id IN (NULL)" in sql
    assert params == ()


def test_missing_table_policy_fails_closed():
    with pytest.raises(SqlPolicyError):
        rewrite_with_row_policies(
            "SELECT amount FROM orders",
            {"customers": policy("owner_id = %s", "u1")},
        )


def test_parse_failure_fails_closed_without_returning_original_sql():
    with pytest.raises(SqlPolicyError):
        rewrite_with_row_policies(
            "SELECT amount FROM orders WHERE owner_id =",
            {"orders": policy("owner_id = %s", "u1")},
        )
