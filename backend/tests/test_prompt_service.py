import pytest

from app.services.prompt_service import (
    build_insight_generation_messages,
)


def test_insight_prompt_includes_question_and_query_results():
    messages = build_insight_generation_messages(
        question="Which region generated the most revenue?",
        query_results={
            "columns": ["region", "total_revenue"],
            "rows": [
                {"region": "North", "total_revenue": 500}
            ],
            "row_count": 1,
        },
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    assert "Which region generated the most revenue?" in messages[1]["content"]
    assert "North" in messages[1]["content"]
    assert "500" in messages[1]["content"]


@pytest.mark.parametrize(
    "question",
    [
        "",
        "   ",
        "x" * 2001,
    ],
)
def test_insight_prompt_rejects_invalid_questions(question):
    with pytest.raises(ValueError):
        build_insight_generation_messages(
            question=question,
            query_results={
                "columns": ["region"],
                "rows": [],
            },
        )


def test_insight_prompt_rejects_invalid_query_results():
    with pytest.raises(ValueError):
        build_insight_generation_messages(
            question="Summarize the results.",
            query_results=[],
        )


@pytest.mark.parametrize(
    "query_results",
    [
        {"columns": ["region"]},
        {"rows": []},
        {"columns": "region", "rows": []},
        {"columns": [], "rows": {}},
    ],
)
def test_insight_prompt_rejects_invalid_result_structure(
    query_results,
):
    with pytest.raises(ValueError):
        build_insight_generation_messages(
            question="Summarize the results.",
            query_results=query_results,
        )


def test_insight_prompt_limits_rows_to_twenty():
    rows = [
        {"region": f"Region {index}", "revenue": index}
        for index in range(30)
    ]

    messages = build_insight_generation_messages(
        question="Summarize revenue.",
        query_results={
            "columns": ["region", "revenue"],
            "rows": rows,
        },
    )

    content = messages[1]["content"]

    assert "Region 19" in content
    assert "Region 20" not in content
    assert '"total_rows_returned": 30' in content
    assert '"sample_rows_included": 20' in content

def test_insight_prompt_enforces_serialized_payload_limit():
    rows = [
        {
            "region": "North",
            "description": "x" * 10000,
        }
        for _ in range(20)
    ]

    messages = build_insight_generation_messages(
        question="Summarize the results.",
        query_results={
            "columns": ["region", "description"],
            "rows": rows,
        },
    )

    content = messages[1]["content"]

    # Extract the JSON payload from the prompt.
    marker = "SQL QUERY RESULTS:\n"
    start = content.index(marker) + len(marker)
    end = content.index("\n\nAnalyze only", start)

    results_json = content[start:end]

    assert len(results_json) <= 12000