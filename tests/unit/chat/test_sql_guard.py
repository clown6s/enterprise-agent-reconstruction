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


def test_accepts_keyword_inside_string_literal():
    validate_sql(
        "SELECT note FROM orders WHERE note = 'please drop this record'",
        allowed_tables={"orders"},
    )


def test_rejects_real_keyword_outside_literal():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT note FROM orders WHERE note = 'x' DROP",
                     allowed_tables={"orders"})


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


def test_allowed_columns_none_skips_column_check():
    # allowed_columns 未启用（None）时不做列校验，是显式选择而非 fail-open。
    validate_sql("SELECT anything FROM orders", allowed_tables={"orders"})


def test_allowed_columns_empty_dict_fails_closed():
    # fail-closed：启用列白名单但目标表无任何已登记列，应拒绝而非放行，
    # 否则 LLM 可编造任意列名（如 create_time）直接执行到数据库才报错。
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT anything FROM orders", allowed_tables={"orders"},
                     allowed_columns={})


def test_allows_column_in_allowlist():
    validate_sql("SELECT amount, region FROM orders",
                 allowed_tables={"orders"},
                 allowed_columns={"orders": {"amount", "region"}})


def test_blocks_column_not_in_allowlist():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT secret FROM orders",
                     allowed_tables={"orders"},
                     allowed_columns={"orders": {"amount", "region"}})


def test_blocks_unauthorized_aliased_column():
    with pytest.raises(SqlPolicyError):
        validate_sql("SELECT o.card_no FROM orders o",
                     allowed_tables={"orders"},
                     allowed_columns={"orders": {"amount"}})


def test_allows_aggregate_function_and_format_columns():
    validate_sql(
        "SELECT SUM(amount) AS total, COUNT(id), "
        "DATE_FORMAT(created_at, '%Y-%m') FROM orders",
        allowed_tables={"orders"},
        allowed_columns={"orders": {"amount", "id", "created_at"}})


def test_allows_order_by_output_alias():
    # total_amount 是 SUM(amount) 的输出别名，ORDER BY 引用它应放行
    validate_sql(
        "SELECT region, SUM(amount) AS total_amount FROM orders "
        "GROUP BY region ORDER BY total_amount DESC",
        allowed_tables={"orders"},
        allowed_columns={"orders": {"amount", "region"}})


def test_allows_having_output_alias():
    validate_sql(
        "SELECT region, SUM(amount) AS total_amount FROM orders "
        "GROUP BY region HAVING total_amount > 100",
        allowed_tables={"orders"},
        allowed_columns={"orders": {"amount", "region"}})


def test_blocks_output_alias_in_where():
    # WHERE 中同名标识符是物理列引用，不能借 SELECT 别名放行
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT SUM(amount) AS total_amount FROM orders "
            "WHERE total_amount > 0",
            allowed_tables={"orders"},
            allowed_columns={"orders": {"amount"}})


def test_join_columns_checked_per_table():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT o.id, c.phone FROM orders o JOIN customers c ON o.id=c.id",
            allowed_tables={"orders", "customers"},
            allowed_columns={"orders": {"id"}, "customers": {"name"}})


def test_join_columns_allowed_per_table():
    validate_sql(
        "SELECT o.amount, c.name FROM orders o "
        "LEFT JOIN customers c ON o.customer_id=c.id",
        allowed_tables={"orders", "customers"},
        allowed_columns={"orders": {"amount", "customer_id"},
                         "customers": {"id", "name"}})


def test_cte_allows_allowed_column():
    validate_sql(
        "WITH recent AS (SELECT amount FROM orders) SELECT amount FROM recent",
        allowed_tables={"orders"},
        allowed_columns={"orders": {"amount"}})


def test_cte_blocks_column_not_allowed():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "WITH r AS (SELECT secret FROM orders) SELECT amount FROM r",
            allowed_tables={"orders"},
            allowed_columns={"orders": {"amount"}})


def test_derived_table_columns_checked_inner():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT x.amount FROM (SELECT secret AS amount FROM orders) x",
            allowed_tables={"orders"},
            allowed_columns={"orders": {"amount"}})


def test_subquery_columns_checked():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT amount FROM orders WHERE id IN "
            "(SELECT secret FROM order_items)",
            allowed_tables={"orders", "order_items"},
            allowed_columns={"orders": {"amount", "id"},
                             "order_items": {"id"}})


def test_union_blocks_column_not_allowed_anywhere():
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT amount FROM orders UNION SELECT secret FROM products",
            allowed_tables={"orders", "products"},
            allowed_columns={"orders": {"amount"}, "products": {"amount"}})


def test_union_allows_allowed_columns():
    validate_sql(
            "SELECT amount FROM orders UNION SELECT amount FROM products",
            allowed_tables={"orders", "products"},
            allowed_columns={"orders": {"amount"}, "products": {"amount"}})


def test_join_missing_column_allowlist_for_one_table_rejected():
    # JOIN 中一张表有列白名单、另一张缺失，fail-closed 应拒绝整体查询。
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT o.amount, c.name FROM orders o "
            "LEFT JOIN customers c ON o.customer_id=c.id",
            allowed_tables={"orders", "customers"},
            allowed_columns={"orders": {"amount", "customer_id"}})


def test_cte_does_not_require_own_column_allowlist():
    # CTE 名称不是物理表，不应被要求有列白名单。
    validate_sql(
        "WITH recent AS (SELECT amount FROM orders) SELECT amount FROM recent",
        allowed_tables={"orders"},
        allowed_columns={"orders": {"amount"}})


def test_subquery_inner_table_missing_allowlist_rejected():
    # 子查询内部引用的表同样必须有列白名单，否则拒绝。
    with pytest.raises(SqlPolicyError):
        validate_sql(
            "SELECT amount FROM orders WHERE id IN "
            "(SELECT secret FROM order_items)",
            allowed_tables={"orders", "order_items"},
            allowed_columns={"orders": {"amount", "id"}})
