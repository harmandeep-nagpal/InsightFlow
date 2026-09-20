import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.dataset import Dataset
from app.services.dataset_service import (
    extract_metadata,
    prepare_dataset,
)

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets"],
)


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are supported.",
        )

    try:
        df = pd.read_csv(file.file)

        df = prepare_dataset(df)

        metadata = extract_metadata(df)

        dataset = Dataset(
            name=file.filename.rsplit(".", 1)[0],
            filename=file.filename,
            row_count=metadata["row_count"],
            column_count=metadata["column_count"],
            column_names=metadata["column_names"],
            data_types=metadata["data_types"],
        )

        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        return {
            "dataset_id": dataset.id,
            "filename": file.filename,
            **metadata,
            "preview": df.head(5).to_dict(orient="records"),
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    except Exception as e:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=f"Could not process CSV: {str(e)}",
        )