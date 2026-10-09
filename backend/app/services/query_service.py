from sqlalchemy import text
from sqlalchemy.orm import Session

import sqlglot
from sqlglot import exp


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


def validate_sql(
    sql: str,
    expected_table: str,
) -> None:

    sql = sql.strip()

    if not sql:
        raise ValueError("SQL query cannot be empty.")

    # Prevent multiple SQL statements.
    if ";" in sql:
        raise ValueError(
            "Multiple SQL statements are not allowed."
        )

    # Prevent SQL comments from bypassing validation.
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError(
            "SQL comments are not allowed."
        )

    try:
        parsed = sqlglot.parse(
            sql,
            read="postgres",
        )
    except Exception as e:
        raise ValueError(
            f"Invalid SQL syntax: {str(e)}"
        )

    # Exactly one SQL statement.
    if len(parsed) != 1:
        raise ValueError(
            "Only one SQL statement is allowed."
        )

    expression = parsed[0]

    # Query must be SELECT.
    if not isinstance(expression, exp.Select):
        raise ValueError(
            "Only SELECT queries are allowed."
        )

    # Reject destructive / modifying SQL expressions.
    for forbidden in FORBIDDEN_EXPRESSIONS:
        if expression.find(forbidden):
            raise ValueError(
                "Only read-only SELECT queries are allowed."
            )

    # Find all tables referenced by the query.
    tables = list(
        expression.find_all(exp.Table)
    )

    if not tables:
        raise ValueError(
            "Query must reference the selected dataset."
        )

    referenced_tables = {
        table.name
        for table in tables
    }

    # Query must only access the selected dataset table.
    if referenced_tables != {expected_table}:
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

    validate_sql(
        sql=sql,
        expected_table=table_name,
    )

    # Wrap the user's SELECT so our result limit
    # cannot be bypassed by a large LIMIT in the query.
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

    rows = [
        dict(row._mapping)
        for row in result
    ]

    columns = list(result.keys())

    return {
        "dataset_id": dataset_id,
        "table_name": table_name,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }