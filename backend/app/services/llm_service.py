import json

import httpx

from app.config import settings


class LLMServiceError(Exception):
    """Raised when the local LLM cannot generate a valid response."""


def _validate_llm_output(content: str) -> dict:
    """
    Parse and validate the JSON returned by the LLM.

    This validates response structure only.
    It does not establish that the generated SQL is safe.
    """

    # Parse the model's JSON response.
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMServiceError(
            "The model returned invalid JSON."
        ) from exc

    # Validate the top-level response structure first.
    if not isinstance(result, dict):
        raise LLMServiceError(
            "The model response must be a JSON object."
        )

    # Validate the explanation field.
    if not isinstance(result.get("explanation"), str):
        raise LLMServiceError(
            "'explanation' must be a string."
        )

    explanation = result["explanation"].strip()

    if not explanation:
        raise LLMServiceError(
            "'explanation' cannot be empty."
        )

    # Ensure the response contains exactly the required fields.
    required_fields = {
        "can_answer",
        "sql",
        "explanation",
    }

    if set(result.keys()) != required_fields:
        raise LLMServiceError(
            "The model response contains missing or unexpected fields."
        )

    # Validate whether the question can be answered.
    if not isinstance(result["can_answer"], bool):
        raise LLMServiceError(
            "'can_answer' must be a boolean."
        )

    sql = result["sql"]

    # Validate the SQL field based on can_answer.
    if result["can_answer"]:
        if not isinstance(sql, str) or not sql.strip():
            raise LLMServiceError(
                "The model must provide SQL when the question is answerable."
            )
    elif sql is not None:
        raise LLMServiceError(
            "SQL must be null when the question is not answerable."
        )

    return {
        "can_answer": result["can_answer"],
        "sql": sql.strip() if isinstance(sql, str) else None,
        "explanation": explanation,
    }


async def generate_sql_response(messages: list[dict]) -> dict:
    """
    Send the existing prompt messages to the local Ollama model.

    Returns a validated response containing:
    - can_answer
    - sql
    - explanation

    This function does not execute SQL.
    """

    # Validate the input messages.
    if not isinstance(messages, list) or not messages:
        raise ValueError(
            "Messages must be a non-empty list."
        )

    for message in messages:
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("role"), str)
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError(
                "Each message must contain string role and content fields."
            )

    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
        },
    }

    # Communicate with the local Ollama API.
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0)
        ) as client:
            response = await client.post(
                url,
                json=payload,
            )

            response.raise_for_status()

    except httpx.ConnectError as exc:
        raise LLMServiceError(
            "Cannot connect to Ollama. Ensure Ollama is running "
            "and its local API is accessible."
        ) from exc

    except httpx.TimeoutException as exc:
        raise LLMServiceError(
            "The local LLM request timed out."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise LLMServiceError(
            f"Ollama returned HTTP {exc.response.status_code}."
        ) from exc

    except httpx.RequestError as exc:
        raise LLMServiceError(
            "A network error occurred while communicating with Ollama."
        ) from exc

    # Extract the model's response content.
    try:
        response_data = response.json()
        content = response_data["message"]["content"]

    except (ValueError, KeyError, TypeError) as exc:
        raise LLMServiceError(
            "Ollama returned an unexpected response format."
        ) from exc

    if not isinstance(content, str):
        raise LLMServiceError(
            "Ollama returned non-text message content."
        )

    # Validate the model output before returning it.
    return _validate_llm_output(content)
