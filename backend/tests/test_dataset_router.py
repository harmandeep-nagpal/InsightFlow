from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.datasets import query_dataset
from app.schemas.query import QueryRequest
from app.models.dataset import Dataset


def test_query_endpoint_does_not_expose_internal_errors():
    dataset = MagicMock(spec=Dataset)
    dataset.id = 1
    dataset.table_name = "dataset_1"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = dataset

    request = QueryRequest(
        sql="SELECT * FROM dataset_1",
        limit=10,
    )

    with patch(
        "app.routers.datasets.execute_dataset_query",
        side_effect=RuntimeError(
            "Sensitive database connection details"
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            query_dataset(
                dataset_id=1,
                request=request,
                db=db,
            )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Query execution failed."
    assert "Sensitive database connection details" not in exc_info.value.detail