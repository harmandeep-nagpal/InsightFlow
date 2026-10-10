from pydantic import BaseModel, Field


class AnalyticsQuestionRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    limit: int = Field(
        default=100,
        ge=1,
        le=500,
    )