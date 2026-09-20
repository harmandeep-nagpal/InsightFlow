import pandas as pd
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