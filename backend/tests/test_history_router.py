from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.dataset import Dataset
from app.models.query_history import QueryHistory
from app.routers.history import get_dataset_query_history


TEST_USER = SimpleNamespace(id=1)


def make_dataset(owner_id=1):
    dataset = MagicMock(spec=Dataset)
    dataset.id = 1
    dataset.owner_id = owner_id
    return dataset


def make_db(dataset, history=None):
    db = MagicMock()

    # First query: dataset ownership lookup.
    db.query.return_value.filter.return_value.first.return_value = dataset

    # Second query: history lookup and pagination.
    db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
        history or []
    )

    return db


def test_history_returns_404_for_missing_dataset():
    db = make_db(None)

    with pytest.raises(HTTPException) as exc_info:
        get_dataset_query_history(
            dataset_id=999,
            limit=20,
            offset=0,
            db=db,
            current_user=TEST_USER,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Dataset not found."


def test_history_returns_404_when_dataset_belongs_to_another_user():
    # The owner-filtered database lookup returns no dataset for this user.
    db = make_db(None)
    another_user = SimpleNamespace(id=2)

    with pytest.raises(HTTPException) as exc_info:
        get_dataset_query_history(
            dataset_id=1,
            limit=20,
            offset=0,
            db=db,
            current_user=another_user,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Dataset not found."


def test_history_returns_empty_list_when_no_queries_exist():
    db = make_db(make_dataset(owner_id=TEST_USER.id))

    result = get_dataset_query_history(
        dataset_id=1,
        limit=20,
        offset=0,
        db=db,
        current_user=TEST_USER,
    )

    assert result == []


def test_history_filters_and_paginates_by_dataset():
    dataset = make_dataset(owner_id=TEST_USER.id)

    record = MagicMock(spec=QueryHistory)
    record.id = 5
    record.dataset_id = 1
    record.question = "What is total revenue?"
    record.generated_sql = "SELECT SUM(revenue) FROM dataset_1"
    record.explanation = "Calculates total revenue."
    record.status = "success"
    record.insights = ["Revenue was 500."]
    record.error_message = None
    record.created_at = datetime(2026, 10, 20, 10, 0, 0)

    db = make_db(dataset, [record])

    result = get_dataset_query_history(
        dataset_id=1,
        limit=10,
        offset=5,
        db=db,
        current_user=TEST_USER,
    )

    assert result == [record]
    assert db.query.return_value.filter.call_count == 2
    db.query.return_value.filter.return_value.order_by.return_value.offset.assert_called_once_with(
        5
    )
    db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.assert_called_once_with(
        10
    )
