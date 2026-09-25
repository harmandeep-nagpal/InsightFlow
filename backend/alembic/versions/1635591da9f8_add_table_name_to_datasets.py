"""add table_name to datasets

Revision ID: 1635591da9f8
Revises: 487bea40b99e
Create Date: 2026-09-23 23:41:10.718926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1635591da9f8'
down_revision: Union[str, Sequence[str], None] = '487bea40b99e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add column as nullable so existing rows can survive
    op.add_column(
        "datasets",
        sa.Column("table_name", sa.String(length=255), nullable=True)
    )

    # 2. Populate existing rows
    op.execute(
        """
        UPDATE datasets
        SET table_name = 'dataset_' || id
        WHERE table_name IS NULL
        """
    )

    # 3. Make column NOT NULL
    op.alter_column(
        "datasets",
        "table_name",
        existing_type=sa.String(length=255),
        nullable=False
    )

    # 4. Ensure every dataset has a unique physical table name
    op.create_unique_constraint(
        "uq_datasets_table_name",
        "datasets",
        ["table_name"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_datasets_table_name",
        "datasets",
        type_="unique"
    )

    op.drop_column("datasets", "table_name")
