import re

from sqlalchemy import (
    BigInteger,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
)
from sqlalchemy.orm import Session

from app.models.dataset import Dataset


def get_dataset_table(
    db: Session,
    dataset: Dataset,
) -> Table:
    """
    Load the physical PostgreSQL table belonging to a dataset.
    """

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

    metadata = MetaData()

    table = Table(
        dataset.table_name,
        metadata,
        autoload_with=db.get_bind(),
    )

    return table


def get_numeric_statistics(
    db: Session,
    table: Table,
    column,
) -> dict | None:
    """
    Calculate statistics for supported numeric columns.
    """

    if not isinstance(
        column.type,
        (Integer, BigInteger, Float),
    ):
        return None

    minimum, maximum, mean_value = db.execute(
        select(
            func.min(column),
            func.max(column),
            func.avg(column),
        ).select_from(table)
    ).one()

    median_value = db.execute(
        select(
            func.percentile_cont(0.5).within_group(
                column
            )
        ).select_from(table)
    ).scalar_one()

    return {
        "min": minimum,
        "max": maximum,
        "mean": (
            float(mean_value)
            if mean_value is not None
            else None
        ),
        "median": (
            float(median_value)
            if median_value is not None
            else None
        ),
    }

def get_categorical_statistics(
    db: Session,
    table: Table,
    column,
    limit: int = 5,
) -> list[dict] | None:
    """
    Return the most frequent non-null values
    for a categorical column.
    """

    if not isinstance(column.type, (String, Text)):
        return None

    statement = (
        select(
            column,
            func.count().label("count"),
        )
        .select_from(table)
        .where(column.is_not(None))
        .group_by(column)
        .order_by(
            func.count().desc(),
            column.asc(),
        )
        .limit(limit)
    )

    results = db.execute(statement).all()

    return [
        {
            "value": row[0],
            "count": row[1],
        }
        for row in results
    ]



def profile_dataset(
    db: Session,
    dataset: Dataset,
) -> dict:
    """
    Calculate dataset-level and column-level statistics
    directly in PostgreSQL.
    """

    table = get_dataset_table(
        db=db,
        dataset=dataset,
    )

    # Count the actual number of rows.
    row_count = db.execute(
        select(
            func.count()
        ).select_from(table)
    ).scalar_one()

    column_profiles = []

    for column in table.columns:

        # Count missing values.
        missing_count = db.execute(
            select(
                func.count()
            )
            .select_from(table)
            .where(column.is_(None))
        ).scalar_one()

        # Count distinct non-null values.
        distinct_count = db.execute(
            select(
                func.count(
                    func.distinct(column)
                )
            ).select_from(table)
        ).scalar_one()

        missing_percentage = (
            round(
                (missing_count / row_count) * 100,
                2,
            )
            if row_count > 0
            else 0.0
        )

        # Calculate statistics for numeric columns.
        statistics = get_numeric_statistics(
            db=db,
            table=table,
            column=column,
        )
        categorical_statistics = get_categorical_statistics(
            db=db,
            table=table,
            column=column,
            limit=5,
        )

        column_profiles.append(
            {
                "column_name": column.name,
                "data_type": str(column.type),
                "nullable": column.nullable,
                "missing_count": missing_count,
                "missing_percentage": missing_percentage,
                "distinct_count": distinct_count,
                "statistics": statistics,
                "categorical_statistics": categorical_statistics,
            }
        )

    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "table_name": dataset.table_name,
        "row_count": row_count,
        "column_count": len(table.columns),
        "columns": column_profiles,
    }

