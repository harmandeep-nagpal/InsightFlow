from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.dataset import Dataset
from app.models.query_history import QueryHistory
from app.schemas.history import QueryHistoryResponse


router = APIRouter(
    prefix="/datasets",
    tags=["Query History"],
)


@router.get(
    "/{dataset_id}/history",
    response_model=list[QueryHistoryResponse],
)
def get_dataset_query_history(
    dataset_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    # Verify that the requested dataset exists.
    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id)
        .first()
    )

    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found.",
        )

    # Return the most recent queries first.
    history = (
        db.query(QueryHistory)
        .filter(QueryHistory.dataset_id == dataset_id)
        .order_by(
            QueryHistory.created_at.desc(),
            QueryHistory.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return history