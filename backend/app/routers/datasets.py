import re
from app.services.profiling_service import profile_dataset
import pandas as pd

from sqlalchemy import (
    MetaData,
    Table,
    inspect,
    select,
)

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

@router.get("/{dataset_id}/schema")
def get_dataset_schema(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    # 1. Retrieve dataset metadata.
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

    # 2. Validate the internally stored table name.
    # Dataset tables are generated as dataset_<dataset_id>.
    expected_table_name = f"dataset_{dataset.id}"

    if dataset.table_name != expected_table_name:
        raise HTTPException(
            status_code=500,
            detail="Dataset table reference is invalid.",
        )

    if not re.fullmatch(
        r"dataset_[1-9][0-9]*",
        dataset.table_name,
    ):
        raise HTTPException(
            status_code=500,
            detail="Dataset table reference is invalid.",
        )

    try:
        # 3. Inspect the actual PostgreSQL table.
        inspector = inspect(db.get_bind())

        if not inspector.has_table(
            dataset.table_name
        ):
            raise HTTPException(
                status_code=500,
                detail="Dataset storage table does not exist.",
            )

        column_metadata = inspector.get_columns(
            dataset.table_name
        )

        # 4. Retrieve primary-key information.
        primary_key_info = inspector.get_pk_constraint(
            dataset.table_name
        )

        primary_key_columns = set(
            primary_key_info.get(
                "constrained_columns"
            ) or []
        )

        # 5. Build structured column information.
        columns = []

        for column in column_metadata:
            column_name = column["name"]

            columns.append(
                {
                    "name": column_name,
                    "data_type": str(
                        column["type"]
                    ),
                    "nullable": column["nullable"],
                    "primary_key": (
                        column_name
                        in primary_key_columns
                    ),
                }
            )

        # 6. Return dataset metadata and actual schema.
        return {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "filename": dataset.filename,
            "table_name": dataset.table_name,
            "row_count": dataset.row_count,
            "column_count": len(columns),
            "columns": columns,
            "created_at": dataset.created_at,
        }

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve dataset schema.",
        )


@router.get("/{dataset_id}/profile")
def get_dataset_profile(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    # 1. Find the dataset metadata.
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
        # 2. Calculate dataset profiling statistics.
        return profile_dataset(
            db=db,
            dataset=dataset,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not profile dataset.",
        )
