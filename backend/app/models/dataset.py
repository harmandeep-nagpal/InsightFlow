from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from app.database.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    owner_id: Mapped[int] = mapped_column(
    Integer,
    ForeignKey("users.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    column_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    column_names: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )

    data_types: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    table_name: Mapped[str] = mapped_column(
    String(255),
    nullable=False,
    unique=True,
)