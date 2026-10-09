from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=1,
        max_length=5000,
    )

    limit: int = Field(
        default=100,
        ge=1,
        le=500,
    )


class QueryResponse(BaseModel):
    dataset_id: int
    table_name: str
    columns: list[str]
    rows: list[dict]
    row_count: int