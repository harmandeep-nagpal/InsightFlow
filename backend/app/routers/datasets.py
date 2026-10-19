import re
from app.services.profiling_service import profile_dataset
import pandas as pd
from app.schemas.analytics import AnalyticsQuestionRequest

from app.services.context_builder import build_dataset_context

from app.services.prompt_service import (
    build_sql_generation_messages,
    build_insight_generation_messages,
)
from app.services.llm_service import (
    generate_sql_response,
    generate_business_insights,
    LLMServiceError,
)
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
import logging
logger = logging.getLogger(__name__)

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

    except Exception:
        db.rollback()

    logger.exception(
        "Unexpected error while uploading dataset."
    )

    raise HTTPException(
        status_code=500,
        detail="Could not process CSV upload.",
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

    except Exception:
        db.rollback()

    logger.exception(
        "Unexpected error while previewing dataset %s.",
        dataset_id,
    )

    raise HTTPException(
        status_code=500,
        detail="Could not preview dataset.",
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

    except Exception:
        logger.exception(
            "Unexpected query execution error for dataset %s.",
            dataset_id,
        )

    raise HTTPException(
        status_code=500,
        detail="Query execution failed.",
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

@router.post("/{dataset_id}/ask")
async def ask_dataset_question(
    dataset_id: int,
    request: AnalyticsQuestionRequest,
    db: Session = Depends(get_db),
):
    # 1. Retrieve the selected dataset.
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

    # 2. Build context from the selected dataset.
    try:
        dataset_context = build_dataset_context(
            db=db,
            dataset=dataset,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not build dataset context.",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not build dataset context.",
        ) from exc

    # 3. Construct the messages for the LLM.
    try:
        messages = build_sql_generation_messages(
            question=request.question,
            dataset_context=dataset_context,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # 4. Ask the local LLM to generate a response.
    try:
        llm_result = await generate_sql_response(messages)

    except LLMServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail="The local LLM could not generate a valid response.",
        ) from exc

    # 5. Return a clear response when the question
    # cannot be answered from the available dataset.
    if not llm_result["can_answer"]:
        return {
            "dataset_id": dataset.id,
            "question": request.question,
            "can_answer": False,
            "explanation": llm_result["explanation"],
            "sql": None,
            "results": None,
        }

    # 6. Validate and execute the generated SQL using
    # the existing query service.
    try:
        query_results = execute_dataset_query(
            db=db,
            sql=llm_result["sql"],
            dataset_id=dataset.id,
            table_name=dataset.table_name,
            limit=request.limit,
        )

    except ValueError as exc:
        # The model-generated SQL failed validation.
        raise HTTPException(
            status_code=502,
            detail="The generated SQL was rejected by the SQL validator.",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The generated query could not be executed.",
        ) from exc

        # 7. Generate insights from the actual query results.
    insights = []

    result_rows = query_results.get("rows", [])

    if result_rows:
        try:
            insight_messages = build_insight_generation_messages(
                question=request.question,
                query_results=query_results,
            )

            insight_response = await generate_business_insights(
                insight_messages
            )

            insights = insight_response["insights"]

        except (LLMServiceError, ValueError):
            # Preserve successfully executed query results if
            # the optional insight-generation step fails.
            logger.warning(
                "Business insight generation failed for dataset %s.",
                dataset.id,
            )

        except Exception:
            # Unexpected failures must not discard query results.
            logger.exception(
                "Unexpected business insight error for dataset %s.",
                dataset.id,
            )

    # 8. Return the SQL explanation, results, and insights.
    return {
        "dataset_id": dataset.id,
        "question": request.question,
        "can_answer": True,
        "explanation": llm_result["explanation"],
        "sql": llm_result["sql"],
        "results": query_results,
        "insights": insights,
    }