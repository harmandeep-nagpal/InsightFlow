import pytest

from app.services.query_service import validate_sql

# -----------------------------

# Valid SQL queries

# -----------------------------

@pytest.mark.parametrize(
"sql",
[
"""
SELECT region, SUM(revenue) AS total_revenue
FROM dataset_1
GROUP BY region
ORDER BY total_revenue DESC
""",
"""
SELECT COUNT(*) AS total_rows
FROM dataset_1
""",
"""
SELECT *
FROM dataset_1
WHERE revenue > 100
LIMIT 10
""",
"""
SELECT *
FROM dataset_1
WHERE region IN (
SELECT region
FROM dataset_1
)
""",
],
)
def test_valid_analytics_queries_are_accepted(sql):
    validate_sql(sql, expected_table="dataset_1")

# -----------------------------

# Invalid SQL queries

# -----------------------------

@pytest.mark.parametrize(
    "sql",
    [
        # Database modification
        "DELETE FROM dataset_1",

        # UNION is rejected by the current SELECT-only policy
        "SELECT * FROM dataset_1 UNION SELECT * FROM dataset_1",

        # Unexpected table
        "SELECT * FROM dataset_2",

        # Schema-qualified table
        "SELECT * FROM public.dataset_1",

        # No dataset reference
        "SELECT 1",

        # Dangerous PostgreSQL function
        "SELECT pg_sleep(1) FROM dataset_1",

        # Dangerous PostgreSQL function with explicit schema
        "SELECT pg_catalog.pg_sleep(1) FROM dataset_1",

        # CTE
        "WITH temp AS (SELECT * FROM dataset_1) SELECT * FROM temp",

        # Multiple statements
        "SELECT * FROM dataset_1; SELECT * FROM dataset_1",

        # SQL comments
        "SELECT * FROM dataset_1 -- comment",

        # Invalid syntax
        "SELECT FROM WHERE",

        # SELECT INTO must not create a new table
        "SELECT revenue INTO dataset_copy FROM dataset_1",

        # Row locking must not be allowed
        "SELECT * FROM dataset_1 FOR UPDATE",
    ],
)


def test_unsafe_queries_are_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, expected_table="dataset_1")
        
# SELECT INTO attempts to create a table from query results
"SELECT revenue INTO dataset_copy FROM dataset_1",

# Row-locking clause should not be allowed for analytics
"SELECT * FROM dataset_1 FOR UPDATE",

# Dangerous function with an explicit schema
"SELECT pg_catalog.pg_sleep(1) FROM dataset_1",
# -----------------------------

# Dataset identifier validation

# -----------------------------

@pytest.mark.parametrize(
"table_name",
[
"dataset_0",
"dataset_01",
"dataset_1; DROP TABLE datasets",
"public.dataset_1",
"datasets",
"",
],
)
def test_invalid_expected_table_names_are_rejected(table_name):
    with pytest.raises(ValueError):
        validate_sql(
        "SELECT * FROM dataset_1",
        expected_table=table_name,
        )

def test_query_must_be_a_string():
    with pytest.raises(ValueError):
        validate_sql(None, expected_table="dataset_1")

def test_empty_query_is_rejected():
    with pytest.raises(ValueError):
        validate_sql("   ", expected_table="dataset_1")
