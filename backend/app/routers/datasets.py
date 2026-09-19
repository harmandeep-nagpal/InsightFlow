import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets"],
)


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):

    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are supported."
        )

    try:
        df = pd.read_csv(file.file)

        return {
            "filename": file.filename,
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": df.columns.tolist(),
            "data_types": {
                column: str(dtype)
                for column, dtype in df.dtypes.items()
            },
            "missing_values": {
                column: int(value)
                for column, value in df.isna().sum().items()
            },
            "preview": df.head(5).to_dict(orient="records"),
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not process CSV: {str(e)}"
        )