import pandas as pd

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    MetaData,
    Table,
    Text,
)


def validate_dataset(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("Dataset is empty.")

    if len(df.columns) == 0:
        raise ValueError("Dataset contains no columns.")

    if df.columns.duplicated().any():
        raise ValueError("Dataset contains duplicate column names.")


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace(r"[^a-z0-9_]", "", regex=True)
    )

    return df


def prepare_dataset(df: pd.DataFrame) -> pd.DataFrame:
    validate_dataset(df)

    df = normalize_column_names(df)

    validate_dataset(df)

    return df


def extract_metadata(df: pd.DataFrame) -> dict:
    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "column_names": df.columns.tolist(),
        "data_types": {
            column: str(dtype)
            for column, dtype in df.dtypes.items()
        },
        "missing_values": {
            column: int(value)
            for column, value in df.isna().sum().items()
        },
    }


def map_pandas_dtype(dtype):
    if pd.api.types.is_integer_dtype(dtype):
        return BigInteger

    if pd.api.types.is_float_dtype(dtype):
        return Float

    if pd.api.types.is_bool_dtype(dtype):
        return Boolean

    if pd.api.types.is_datetime64_any_dtype(dtype):
        return DateTime

    return Text


def create_dataset_table(
    df: pd.DataFrame,
    dataset_id: int,
    metadata: MetaData,
) -> Table:

    table_name = f"dataset_{dataset_id}"

    columns = []

    for column_name in df.columns:
        column_type = map_pandas_dtype(
            df[column_name].dtype
        )

        columns.append(
            Column(
                column_name,
                column_type,
                nullable=True,
            )
        )

    table = Table(
        table_name,
        metadata,
        *columns,
    )

    return table


def create_physical_dataset_table(
    db,
    df: pd.DataFrame,
    dataset_id: int,
) -> Table:

    metadata = MetaData()

    table = create_dataset_table(
        df=df,
        dataset_id=dataset_id,
        metadata=metadata,
    )

    table.create(
        bind=db.get_bind(),
        checkfirst=True,
    )

    return table


def insert_dataset_rows(
    db,
    table: Table,
    df: pd.DataFrame,
) -> None:

    records = df.to_dict(
        orient="records"
    )

    if records:
        db.execute(
            table.insert(),
            records,
        )