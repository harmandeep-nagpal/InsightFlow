"""create query history table

Revision ID: d55777d06aa0
Revises: 1635591da9f8
Create Date: 2026-10-20 21:28:55.840924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd55777d06aa0'
down_revision: Union[str, Sequence[str], None] = '1635591da9f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "query_history",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "generated_sql",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "explanation",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "insights",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "error_message",
            sa.String(length=500),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_query_history_dataset_id",
        "query_history",
        ["dataset_id"],
    )

    op.create_index(
        "ix_query_history_created_at",
        "query_history",
        ["created_at"],
    )

    op.create_index(
        "ix_query_history_dataset_created",
        "query_history",
        ["dataset_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_query_history_dataset_created",
        table_name="query_history",
    )

    op.drop_index(
        "ix_query_history_created_at",
        table_name="query_history",
    )

    op.drop_index(
        "ix_query_history_dataset_id",
        table_name="query_history",
    )

    op.drop_table("query_history")