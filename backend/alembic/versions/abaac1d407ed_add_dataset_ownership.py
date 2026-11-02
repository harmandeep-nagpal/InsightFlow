"""add dataset ownership

Revision ID: abaac1d407ed
Revises: 4892deb11d63
Create Date: 2026-11-02 11:21:54.783627

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "abaac1d407ed"
down_revision: Union[str, Sequence[str], None] = "4892deb11d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable ownership first so existing datasets remain intact.
    op.add_column(
        "datasets",
        sa.Column("owner_id", sa.Integer(), nullable=True),
    )

    # Link datasets to users.
    op.create_foreign_key(
        "fk_datasets_owner_id_users",
        "datasets",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Improve queries that filter datasets by owner.
    op.create_index(
        "ix_datasets_owner_id",
        "datasets",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_datasets_owner_id", table_name="datasets")

    op.drop_constraint(
        "fk_datasets_owner_id_users",
        "datasets",
        type_="foreignkey",
    )

    op.drop_column("datasets", "owner_id")