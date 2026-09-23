import pandas as pd

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)

from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.dataset import Dataset

from app.services.dataset_service import (
    create_physical_dataset_table,
    extract_metadata,
    insert_dataset_rows,
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
        # 1. Read CSV
        df = pd.read_csv(file.file)

        # 2. Validate + normalize
        df = prepare_dataset(df)

        # 3. Extract metadata
        metadata = extract_metadata(df)

        # 4. Create dataset metadata record
        dataset = Dataset(
            name=file.filename.rsplit(".", 1)[0],
            filename=file.filename,
            row_count=metadata["row_count"],
            column_count=metadata["column_count"],
            column_names=metadata["column_names"],
            data_types=metadata["data_types"],
            table_name="pending",
        )

        db.add(dataset)

        # 5. Send INSERT to PostgreSQL
        #    This generates dataset.id
        db.flush()

        # 6. Generate safe table name
        dataset.table_name = f"dataset_{dataset.id}"

        # 7. Create physical PostgreSQL table
        table = create_physical_dataset_table(
            db=db,
            df=df,
            dataset_id=dataset.id,
        )

        # 8. Insert actual CSV rows
        insert_dataset_rows(
            db=db,
            table=table,
            df=df,
        )

        # 9. Commit everything
        db.commit()

        # 10. Refresh SQLAlchemy object
        db.refresh(dataset)

        return {
            "dataset_id": dataset.id,
            "filename": file.filename,
            "table_name": dataset.table_name,
            **metadata,
            "preview": df.head(5).to_dict(
                orient="records"
            ),
        }

    except ValueError as e:
        db.rollback()

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