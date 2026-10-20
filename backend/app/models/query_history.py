from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    dataset_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    generated_sql: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )

    insights: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_query_history_dataset_created",
            "dataset_id",
            "created_at",
        ),
    )