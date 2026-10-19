import pytest
import httpx
import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm_service import (
    LLMServiceError,
    _validate_llm_output,
    _validate_insight_output,
    generate_sql_response,
    generate_business_insights,
)


def test_valid_response_is_accepted_and_explanation_trimmed():
    content = (
        '{"can_answer": false, "sql": null, '
        '"explanation": "  Not enough information.  "}'
    )

    result = _validate_llm_output(content)

    assert result == {
        "can_answer": False,
        "sql": None,
        "explanation": "Not enough information.",
    }


@pytest.mark.parametrize(
    "content",
    [
        "not valid json",
        "[]",
        "123",
        '{"can_answer": false, "sql": null}',
        '{"can_answer": false, "sql": null, "explanation": 123}',
        '{"can_answer": false, "sql": null, "explanation": "   "}',
        '{"can_answer": "yes", "sql": null, "explanation": "Test"}',
        '{"can_answer": false, "sql": "SELECT 1", "explanation": "Test"}',
        (
            '{"can_answer": false, "sql": null, '
            '"explanation": "Test", "extra": true}'
        ),
    ],
)
def test_invalid_responses_are_rejected(content):
    with pytest.raises(LLMServiceError):
        _validate_llm_output(content)


def test_answerable_response_requires_sql():
    content = (
        '{"can_answer": true, "sql": null, '
        '"explanation": "Sales can be calculated."}'
    )

    with pytest.raises(LLMServiceError):
        _validate_llm_output(content)


def test_valid_answerable_response_is_accepted():
    content = (
        '{"can_answer": true, "sql": " SELECT 1 ", '
        '"explanation": " Query generated. "}'
    )

    result = _validate_llm_output(content)

    assert result["can_answer"] is True
    assert result["sql"] == "SELECT 1"
    assert result["explanation"] == "Query generated."

@pytest.mark.asyncio
async def test_generate_sql_response_success():
    messages = [
        {
            "role": "user",
            "content": "Show total sales by region.",
        }
    ]

    ollama_content = {
        "can_answer": True,
        "sql": "SELECT region, SUM(sales) AS total_sales "
               "FROM dataset_1 GROUP BY region",
        "explanation": "Calculates total sales for each region.",
    }

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": __import__("json").dumps(ollama_content)
        }
    }
    mock_response.raise_for_status.return_value = None

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        result = await generate_sql_response(messages)

    assert result["can_answer"] is True
    assert "SUM(sales)" in result["sql"]
    assert result["explanation"] == (
        "Calculates total sales for each region."
    )

    mock_client.post.assert_awaited_once()

@pytest.mark.asyncio
async def test_generate_sql_response_connection_error():
    messages = [{"role": "user", "content": "Show total sales."}]

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError(
            "Connection refused"
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(LLMServiceError, match="Cannot connect to Ollama"):
            await generate_sql_response(messages)


@pytest.mark.asyncio
async def test_generate_sql_response_timeout():
    messages = [{"role": "user", "content": "Show total sales."}]

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ReadTimeout(
            "Request timed out"
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(
            LLMServiceError,
            match="local LLM request timed out",
        ):
            await generate_sql_response(messages)


@pytest.mark.asyncio
async def test_generate_sql_response_http_error():
    messages = [{"role": "user", "content": "Show total sales."}]

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        response=httpx.Response(500),
    )

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(LLMServiceError, match="Ollama returned HTTP 500"):
            await generate_sql_response(messages)


@pytest.mark.asyncio
async def test_generate_sql_response_malformed_body():
    messages = [{"role": "user", "content": "Show total sales."}]

    mock_response = MagicMock()
    mock_response.json.return_value = {"unexpected": "structure"}
    mock_response.raise_for_status.return_value = None

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(
            LLMServiceError,
            match="unexpected response format",
        ):
            await generate_sql_response(messages)


@pytest.mark.asyncio
async def test_generate_sql_response_invalid_model_json():
    messages = [{"role": "user", "content": "Show total sales."}]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": "not valid json"}
    }
    mock_response.raise_for_status.return_value = None

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(LLMServiceError, match="invalid JSON"):
            await generate_sql_response(messages)

def test_valid_insight_response_is_accepted():
    content = (
        '{"insights": ['
        '"North generated the highest revenue.",'
        '"Two regions returned results."'
        ']}'
    )

    result = _validate_insight_output(content)

    assert result == {
        "insights": [
            "North generated the highest revenue.",
            "Two regions returned results.",
        ]
    }


def test_empty_insight_list_is_accepted():
    assert _validate_insight_output(
        '{"insights": []}'
    ) == {"insights": []}


@pytest.mark.parametrize(
    "content",
    [
        "not valid JSON",
        "[]",
        "{}",
        '{"insights": "not a list"}',
        '{"insights": [123]}',
        '{"insights": ["   "]}',
        '{"insights": [], "extra": true}',
        '{"insights": ["a", "b", "c", "d", "e", "f"]}',
        '{"insights": ["' + ("x" * 1001) + '"]}',
    ],
)
def test_invalid_insight_responses_are_rejected(content):
    with pytest.raises(LLMServiceError):
        _validate_insight_output(content)

@pytest.mark.asyncio
async def test_generate_business_insights_success():
    messages = [
        {
            "role": "user",
            "content": "Analyze these query results.",
        }
    ]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": (
                '{"insights": '
                '["North generated the highest revenue."]}'
            )
        }
    }
    mock_response.raise_for_status.return_value = None

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_client_class.return_value.__aenter__.return_value = (
            mock_client
        )
        mock_client_class.return_value.__aexit__.return_value = None

        result = await generate_business_insights(messages)

    assert result == {
        "insights": [
            "North generated the highest revenue."
        ]
    }

    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_business_insights_connection_error():
    messages = [
        {
            "role": "user",
            "content": "Analyze these query results.",
        }
    ]

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError(
            "Connection refused"
        )

        mock_client_class.return_value.__aenter__.return_value = (
            mock_client
        )
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(
            LLMServiceError,
            match="Cannot connect to Ollama",
        ):
            await generate_business_insights(messages)


@pytest.mark.asyncio
async def test_generate_business_insights_timeout():
    messages = [
        {
            "role": "user",
            "content": "Analyze these query results.",
        }
    ]

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ReadTimeout(
            "Request timed out"
        )

        mock_client_class.return_value.__aenter__.return_value = (
            mock_client
        )
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(
            LLMServiceError,
            match="local LLM request timed out",
        ):
            await generate_business_insights(messages)


@pytest.mark.asyncio
async def test_generate_business_insights_malformed_response():
    messages = [
        {
            "role": "user",
            "content": "Analyze these query results.",
        }
    ]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "unexpected": "structure"
    }
    mock_response.raise_for_status.return_value = None

    with patch(
        "app.services.llm_service.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_client_class.return_value.__aenter__.return_value = (
            mock_client
        )
        mock_client_class.return_value.__aexit__.return_value = None

        with pytest.raises(
            LLMServiceError,
            match="unexpected response format",
        ):
            await generate_business_insights(messages)