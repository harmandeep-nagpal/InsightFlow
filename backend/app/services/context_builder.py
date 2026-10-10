import re

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.services.profiling_service import profile_dataset


def build_dataset_context(
    db: Session,
    dataset: Dataset,
) -> dict:
    """
    Build structured dataset context for natural-language
    analytics and SQL generation.

    Includes:
    - Dataset metadata
    - Actual PostgreSQL schema
    - Primary-key information
    - Dataset profiling statistics

    Does not send data to an LLM or execute generated SQL.
    """

    # 1. Validate the dataset's physical table reference.
    expected_table_name = f"dataset_{dataset.id}"

    if dataset.table_name != expected_table_name:
        raise ValueError(
            "Dataset table reference is invalid."
        )

    if not re.fullmatch(
        r"dataset_[1-9][0-9]*",
        dataset.table_name,
    ):
        raise ValueError(
            "Dataset table reference is invalid."
        )

    # 2. Inspect the actual PostgreSQL schema.
    inspector = inspect(db.get_bind())

    if not inspector.has_table(dataset.table_name):
        raise ValueError(
            "Dataset storage table does not exist."
        )

    column_metadata = inspector.get_columns(
        dataset.table_name
    )

    if not column_metadata:
        raise ValueError(
            "Dataset does not contain any columns."
        )

    # 3. Identify primary-key columns.
    primary_key_info = inspector.get_pk_constraint(
        dataset.table_name
    )

    primary_key_columns = set(
        primary_key_info.get(
            "constrained_columns"
        ) or []
    )

    # 4. Build schema metadata from the real database.
    columns = []

    for column in column_metadata:
        column_name = column["name"]

        columns.append(
            {
                "name": column_name,
                "data_type": str(column["type"]),
                "nullable": column["nullable"],
                "primary_key": (
                    column_name in primary_key_columns
                ),
            }
        )

    # 5. Retrieve statistics from the existing profiling service.
    profiling = profile_dataset(
        db=db,
        dataset=dataset,
    )

    # 6. Return the complete context.
    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "filename": dataset.filename,
            "table_name": dataset.table_name,
            "row_count": profiling["row_count"],
            "column_count": len(columns),
        },
        "schema": {
            "columns": columns,
        },
        "profiling": profiling,
    }