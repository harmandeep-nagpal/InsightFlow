
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.datasets import (
    ask_dataset_question,
    query_dataset,
)
from app.schemas.analytics import AnalyticsQuestionRequest
from app.schemas.query import QueryRequest
from app.models.dataset import Dataset
from app.services.llm_service import LLMServiceError



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

def make_analytics_request():
    return AnalyticsQuestionRequest(
        question="What is the total revenue?",
        limit=10,
    )


def make_dataset_mock():
    dataset = MagicMock(spec=Dataset)
    dataset.id = 1
    dataset.table_name = "dataset_1"
    return dataset


def make_database_mock(dataset):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = dataset
    return db


@pytest.mark.asyncio
async def test_ask_endpoint_returns_404_for_missing_dataset():
    db = make_database_mock(None)

    with pytest.raises(HTTPException) as exc_info:
        await ask_dataset_question(
            dataset_id=999,
            request=make_analytics_request(),
            db=db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Dataset not found."


@pytest.mark.asyncio
async def test_ask_endpoint_returns_502_when_llm_fails():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        side_effect=LLMServiceError("Internal Ollama details"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ask_dataset_question(
                dataset_id=1,
                request=make_analytics_request(),
                db=db,
            )

    assert exc_info.value.status_code == 502
    assert "Internal Ollama details" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_ask_endpoint_does_not_execute_sql_when_unanswerable():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": False,
            "sql": None,
            "explanation": "The dataset does not contain the required information.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
    ) as mock_execute:
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["can_answer"] is False
    assert result["sql"] is None
    assert result["results"] is None
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_ask_endpoint_returns_502_when_generated_sql_is_rejected():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT * FROM dataset_2",
            "explanation": "Generated query.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        side_effect=ValueError("Unexpected table."),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ask_dataset_question(
                dataset_id=1,
                request=make_analytics_request(),
                db=db,
            )

    assert exc_info.value.status_code == 502
    assert "Unexpected table." not in exc_info.value.detail


@pytest.mark.asyncio
async def test_ask_endpoint_returns_results_from_query_service():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["region", "total_revenue"],
        "rows": [{"region": "North", "total_revenue": 500}],
        "row_count": 1,
    }

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT region, SUM(revenue) AS total_revenue FROM dataset_1 GROUP BY region",
            "explanation": "Calculates revenue by region.",
        },
    ), patch(
            "app.routers.datasets.execute_dataset_query",
            return_value=query_results,
        ) as mock_execute, patch(
            "app.routers.datasets.generate_business_insights",
            new_callable=AsyncMock,
            return_value={
                "insights": [
                    "North generated 500 in revenue."
                ]
            },
        ) as mock_insights:
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["can_answer"] is True
    assert result["results"] == query_results
    assert result["explanation"] == "Calculates revenue by region."

    mock_execute.assert_called_once_with(
        db=db,
        sql="SELECT region, SUM(revenue) AS total_revenue FROM dataset_1 GROUP BY region",
        dataset_id=1,
        table_name="dataset_1",
        limit=10,
    )

    assert result["insights"] == [
        "North generated 500 in revenue."
    ]

    mock_insights.assert_awaited_once()

@pytest.mark.asyncio
async def test_ask_endpoint_preserves_results_when_insight_generation_fails():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["region", "total_revenue"],
        "rows": [
            {"region": "North", "total_revenue": 500}
        ],
        "row_count": 1,
    }

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[
            {"role": "user", "content": "test"}
        ],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT region, SUM(revenue) AS total_revenue FROM dataset_1 GROUP BY region",
            "explanation": "Calculates revenue by region.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        return_value=query_results,
    ), patch(
        "app.routers.datasets.generate_business_insights",
        new_callable=AsyncMock,
        side_effect=LLMServiceError("Internal Ollama error"),
    ):
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["can_answer"] is True
    assert result["results"] == query_results
    assert result["insights"] == []

@pytest.mark.asyncio
async def test_ask_endpoint_skips_insight_generation_for_empty_results():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["region", "total_revenue"],
        "rows": [],
        "row_count": 0,
    }

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[
            {"role": "user", "content": "test"}
        ],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT region, SUM(revenue) AS total_revenue FROM dataset_1 GROUP BY region",
            "explanation": "Calculates revenue by region.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        return_value=query_results,
    ), patch(
        "app.routers.datasets.generate_business_insights",
        new_callable=AsyncMock,
    ) as mock_insights:
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["results"] == query_results
    assert result["insights"] == []

    mock_insights.assert_not_awaited()

@pytest.mark.asyncio
async def test_ask_endpoint_persists_successful_query_history():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["total_revenue"],
        "rows": [],
        "row_count": 0,
    }

    generated_sql = "SELECT SUM(revenue) AS total_revenue FROM dataset_1"
    explanation = "Calculates total revenue."

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": generated_sql,
            "explanation": explanation,
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        return_value=query_results,
    ):
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    history = db.add.call_args.args[0]

    assert result["can_answer"] is True
    assert result["results"] == query_results

    assert history.dataset_id == 1
    assert history.question == "What is the total revenue?"
    assert history.generated_sql == generated_sql
    assert history.explanation == explanation
    assert history.status == "success"
    assert history.insights == []
    assert history.error_message is None

    # One commit creates the pending record.
    # Another commits the final outcome.
    assert db.commit.call_count == 2

@pytest.mark.asyncio
async def test_ask_endpoint_persists_unanswerable_question():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    explanation = "The dataset does not contain the required information."

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": False,
            "sql": None,
            "explanation": explanation,
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
    ) as mock_execute:
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    history = db.add.call_args.args[0]

    assert result["can_answer"] is False
    assert result["explanation"] == explanation

    assert history.status == "cannot_answer"
    assert history.explanation == explanation
    assert history.generated_sql is None

    mock_execute.assert_not_called()

@pytest.mark.asyncio
async def test_ask_endpoint_continues_when_history_creation_fails():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["total_revenue"],
        "rows": [],
        "row_count": 0,
    }

    db.commit.side_effect = RuntimeError(
        "History database write failed"
    )

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT SUM(revenue) FROM dataset_1",
            "explanation": "Calculates total revenue.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        return_value=query_results,
    ) as mock_execute:
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["can_answer"] is True
    assert result["results"] == query_results

    mock_execute.assert_called_once()
    db.rollback.assert_called()

@pytest.mark.asyncio
async def test_ask_endpoint_preserves_results_when_history_finalization_fails():
    dataset = make_dataset_mock()
    db = make_database_mock(dataset)

    query_results = {
        "dataset_id": 1,
        "table_name": "dataset_1",
        "columns": ["total_revenue"],
        "rows": [],
        "row_count": 0,
    }

    # The first commit creates the pending history record.
    # The second commit fails while updating its final status.
    db.commit.side_effect = [
        None,
        RuntimeError("History finalization failed"),
    ]

    with patch(
        "app.routers.datasets.build_dataset_context",
        return_value={
            "dataset": {},
            "schema": {},
            "profiling": {},
        },
    ), patch(
        "app.routers.datasets.build_sql_generation_messages",
        return_value=[{"role": "user", "content": "test"}],
    ), patch(
        "app.routers.datasets.generate_sql_response",
        new_callable=AsyncMock,
        return_value={
            "can_answer": True,
            "sql": "SELECT SUM(revenue) FROM dataset_1",
            "explanation": "Calculates total revenue.",
        },
    ), patch(
        "app.routers.datasets.execute_dataset_query",
        return_value=query_results,
    ):
        result = await ask_dataset_question(
            dataset_id=1,
            request=make_analytics_request(),
            db=db,
        )

    assert result["can_answer"] is True
    assert result["results"] == query_results

    assert db.commit.call_count == 2
    db.rollback.assert_called()