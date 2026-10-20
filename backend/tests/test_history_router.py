from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.dataset import Dataset
from app.models.query_history import QueryHistory
from app.routers.history import get_dataset_query_history


def make_dataset():
    dataset = MagicMock(spec=Dataset)
    dataset.id = 1
    return dataset


def make_db(dataset, history=None):
    db = MagicMock()

    db.query.return_value.filter.return_value.first.return_value = (
        dataset
    )

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
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Dataset not found."


def test_history_returns_empty_list_when_no_queries_exist():
    db = make_db(make_dataset())

    result = get_dataset_query_history(
        dataset_id=1,
        limit=20,
        offset=0,
        db=db,
    )

    assert result == []


def test_history_filters_and_paginates_by_dataset():
    dataset = make_dataset()

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
    )

    assert result == [record]

    db.query.return_value.filter.assert_called()
    db.query.return_value.filter.return_value.order_by.return_value.offset.assert_called_once_with(
        5
    )

    db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.assert_called_once_with(
        10
    )