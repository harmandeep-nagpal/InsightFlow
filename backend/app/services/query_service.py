import re

import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


# Maximum execution time for a single analytics query.
QUERY_TIMEOUT_MS = 5000

# Enforce the same maximum as the analytics request schema.
MAX_QUERY_LIMIT = 500

# Only generated dataset table names are accepted.
DATASET_TABLE_PATTERN = re.compile(r"^dataset_[1-9]\d*$")


FORBIDDEN_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Grant,
    exp.Revoke,
    exp.Merge,
)


# These functions are unnecessary for ordinary analytics and can
# introduce delays, database changes, or access to server resources.
FORBIDDEN_FUNCTIONS = {
    "PG_SLEEP",
    "PG_READ_FILE",
    "PG_READ_BINARY_FILE",
    "PG_LS_DIR",
    "PG_STAT_FILE",
    "PG_RELOAD_CONF",
    "PG_TERMINATE_BACKEND",
    "PG_CANCEL_BACKEND",
    "PG_ADVISORY_LOCK",
    "PG_ADVISORY_XACT_LOCK",
    "PG_TRY_ADVISORY_LOCK",
    "NEXTVAL",
    "SETVAL",
    "SET_CONFIG",
}


def validate_sql(
    sql: str,
    expected_table: str,
) -> None:
    """
    Validate an analytics query before execution.

    Only SELECT queries that reference the expected dataset table
    are accepted.
    """

    if not isinstance(sql, str):
        raise ValueError("SQL query must be a string.")

    sql = sql.strip()

    if not sql:
        raise ValueError("SQL query cannot be empty.")

    # Validate the expected identifier before using it elsewhere.
    if not DATASET_TABLE_PATTERN.fullmatch(expected_table):
        raise ValueError("Invalid dataset table name.")

    # Reject multiple statements and SQL comments.
    if ";" in sql:
        raise ValueError(
            "Multiple SQL statements are not allowed."
        )

    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError(
            "SQL comments are not allowed."
        )

    try:
        parsed = sqlglot.parse(
            sql,
            read="postgres",
        )
    except Exception as exc:
        raise ValueError(
            "Invalid SQL syntax."
        ) from exc

    # Exactly one SQL statement must be present.
    if len(parsed) != 1 or parsed[0] is None:
        raise ValueError(
            "Only one SQL statement is allowed."
        )

    expression = parsed[0]

    # The outer query must be a SELECT.
    if not isinstance(expression, exp.Select):
        raise ValueError(
            "Only SELECT queries are allowed."
        )

    # Reject data modification and database administration.
    for forbidden in FORBIDDEN_EXPRESSIONS:
        if expression.find(forbidden):
            raise ValueError(
                "Only read-only SELECT queries are allowed."
            )

    # Reject CTEs for now. This keeps table-reference validation
    # straightforward and avoids ambiguous CTE/table-name handling.
    if expression.find(exp.With):
        raise ValueError(
            "Common table expressions (WITH) are not allowed."
        )

    # Reject functions that are inappropriate for analytics queries.
    for function in expression.find_all(exp.Func):
        function_name = function.sql_name().upper()

        if function_name == "ANONYMOUS":
            function_name = getattr(
                function,
                "name",
                "",
            ).upper()

        if function_name in FORBIDDEN_FUNCTIONS:
            raise ValueError(
                f"Function '{function_name}' is not allowed."
            )

    # Find every table reference, including references in subqueries.
    tables = list(
        expression.find_all(exp.Table)
    )

    if not tables:
        raise ValueError(
            "Query must reference the selected dataset."
        )

    for table in tables:
        # Reject references such as public.dataset_2 or
        # another_database.public.dataset_2.
        if table.db or table.catalog:
            raise ValueError(
                "Schema-qualified and database-qualified "
                "table references are not allowed."
            )

        if table.name != expected_table:
            raise ValueError(
                f"Query can only access table '{expected_table}'."
            )


def execute_dataset_query(
    db: Session,
    sql: str,
    dataset_id: int,
    table_name: str,
    limit: int,
) -> dict:
    """
    Validate and execute an analytics query with a result limit
    and PostgreSQL statement timeout.
    """

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_QUERY_LIMIT
    ):
        raise ValueError(
            f"Query limit must be between 1 and {MAX_QUERY_LIMIT}."
        )

    validate_sql(
        sql=sql,
        expected_table=table_name,
    )

    # PostgreSQL applies this timeout locally to the current
    # transaction. It resets when the transaction ends.
    try:
        db.execute(
            text(
                "SELECT set_config("
                "'statement_timeout', :timeout, true"
                ")"
            ),
            {
                "timeout": f"{QUERY_TIMEOUT_MS}ms",
            },
        )

        # Wrap the query so its returned row count cannot exceed
        # our application-enforced limit.
        wrapped_sql = f"""
            SELECT *
            FROM ({sql}) AS query_result
            LIMIT :result_limit
        """

        result = db.execute(
            text(wrapped_sql),
            {
                "result_limit": limit,
            },
        )

        columns = list(result.keys())

        rows = [
            dict(row._mapping)
            for row in result
        ]

        return {
            "dataset_id": dataset_id,
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    except SQLAlchemyError:
        # A PostgreSQL timeout or query error can leave the
        # current transaction in a failed state.
        db.rollback()
        raise