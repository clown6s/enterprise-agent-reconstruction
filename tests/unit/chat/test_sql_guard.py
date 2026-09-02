"""Unit tests for the read-only SQL guard."""
import pytest

from app.chat.application.nl2sql.sql_guard import validate_sql
from app.chat.domain.exceptions import SqlPolicyError


def test_rejects_non_select():
    with pytest.raises(SqlPolicyError):
        validate_sql("DELETE FROM orders", allowed_tables={"orders"})


def test_rejects_blocked_keywords():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT * FROM orders; DROP TABLE orders", allowed_tables={"orders"})


def test_rejects_select_star():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT * FROM orders", allowed_tables={"orders"})


def test_accepts_single_allowed_table():
    validate_sql("SELECT amount FROM orders", allowed_tables={"orders"})


def test_accepts_function_args_not_treated_as_tables():
    validate_sql("SELECT MAX(amount) FROM orders", allowed_tables={"orders"})


def test_accepts_all_allowed_tables_join():
    validate_sql(
        "SELECT o.order_id, c.name FROM orders o LEFT JOIN customers c ON o.customer_id=c.id",
        allowed_tables={"orders", "customers"},
    )


def test_rejects_unauthorized_join_table():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT o.id, u.name FROM orders o JOIN users u ON o.user_id=u.id",
            allowed_tables={"orders"},
        )


def test_rejects_unauthorized_union_table():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT id FROM orders UNION SELECT id FROM products",
            allowed_tables={"orders"},
        )


def test_rejects_unauthorized_comma_list_table():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT amount FROM orders, secrets", allowed_tables={"orders"})


def test_cte_name_not_treated_as_unauthorized_table():
    validate_sql(
        "WITH recent AS (SELECT amount FROM orders) SELECT amount FROM recent",
        allowed_tables={"orders"},
    )


def test_empty_allowlist_rejected():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT 1", allowed_tables=set())


def test_empty_allowlist_no_reference_rejected():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT 1", allowed_tables={"orders"})


def test_blocks_sensitive_column_in_select():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT customer_phone FROM orders",
                     allowed_tables={"orders"},
                     blocked_columns={"orders": {"customer_phone"}})


def test_blocks_sensitive_column_in_where():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT amount FROM orders WHERE customer_phone='123'",
                     allowed_tables={"orders"},
                     blocked_columns={"orders": {"customer_phone"}})


def test_blocks_sensitive_column_with_alias():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT o.card_no FROM orders o",
                     allowed_tables={"orders"},
                     blocked_columns={"orders": {"card_no"}})


def test_allows_query_without_sensitive_column():
    validate_sql("SELECT COUNT(amount), region FROM orders GROUP BY region",
                 allowed_tables={"orders"},
                 blocked_columns={"orders": {"customer_phone"}})


def test_sensitive_column_in_literal_not_false_positive():
    validate_sql("SELECT amount FROM orders WHERE note='customer_phone'",
                 allowed_tables={"orders"},
                 blocked_columns={"orders": {"customer_phone"}})
