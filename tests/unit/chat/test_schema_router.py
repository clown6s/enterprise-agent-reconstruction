"""schema_router 请求模型的输入校验测试。"""
import pytest
from pydantic import ValidationError

from app.chat.api.schema_router import (
    ColumnEntry, ColumnsRequest, JoinEntry, JoinsRequest,
)


def test_column_entry_requires_required_fields():
    with pytest.raises(ValidationError):
        ColumnEntry(data_type="int")


def test_column_entry_accepts_valid():
    col = ColumnEntry(column_name="amount", data_type="decimal", business_name="金额")
    assert col.column_name == "amount"
    assert col.selectable is True


def test_columns_request_requires_at_least_one_column():
    with pytest.raises(ValidationError):
        ColumnsRequest(table="orders", columns=[])


def test_join_entry_requires_table():
    with pytest.raises(ValidationError):
        JoinEntry(columns={"customer_id": "id"})


def test_join_entry_rejects_empty_column_map():
    with pytest.raises(ValidationError):
        JoinEntry(table="customers", columns={})


def test_joins_request_allows_empty_list():
    req = JoinsRequest(table="orders", joins=[])
    assert req.joins == []
