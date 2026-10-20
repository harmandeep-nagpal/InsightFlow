from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QueryHistoryResponse(BaseModel):
    id: int
    dataset_id: int
    question: str
    generated_sql: str | None
    explanation: str | None
    status: str
    insights: list[str]
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)