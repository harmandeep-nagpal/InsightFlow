import pandas as pd
from sqlalchemy import MetaData, Table, select
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from app.schemas.query import (
    QueryRequest,
    QueryResponse,
)

from app.services.query_service import (
    execute_dataset_query,
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

@router.get("/{dataset_id}/preview")
def preview_dataset(
    dataset_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    # Prevent unreasonable requests
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 100.",
        )

    # Find dataset metadata
    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id)
        .first()
    )

    if not dataset:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found.",
        )

    try:
        # Load the physical dataset table
        metadata = MetaData()

        table = Table(
            dataset.table_name,
            metadata,
            autoload_with=db.get_bind(),
        )

        # Query only requested number of rows
        statement = select(table).limit(limit)

        result = db.execute(statement)

        rows = [
            dict(row._mapping)
            for row in result
        ]

        return {
            "dataset_id": dataset.id,
            "table_name": dataset.table_name,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "columns": dataset.column_names,
            "rows": rows,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not preview dataset: {str(e)}",
        )

@router.post(
    "/{dataset_id}/query",
    response_model=QueryResponse,
)
def query_dataset(
    dataset_id: int,
    request: QueryRequest,
    db: Session = Depends(get_db),
):
    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id)
        .first()
    )

    if not dataset:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found.",
        )

    try:
        return execute_dataset_query(
            db=db,
            sql=request.sql,
            dataset_id=dataset.id,
            table_name=dataset.table_name,
            limit=request.limit,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {str(e)}",
        )