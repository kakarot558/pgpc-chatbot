"""tuition fees and enrollment counts

Revision ID: c3f8a1d27e55
Revises: b7e2a4c91d10
Create Date: 2026-11-04 20:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3f8a1d27e55"
down_revision: Union[str, Sequence[str], None] = "b7e2a4c91d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The app may already have created these at start-up (app/database/ensure_schema.py), so check first.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    stamps = lambda: [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]
    if "tuition_fees" not in tables:
        op.create_table(
            "tuition_fees",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("program", sa.String(length=20), nullable=False, index=True),
            sa.Column("residency", sa.String(length=20), nullable=False),
            sa.Column("year_level", sa.Integer(), nullable=False),
            sa.Column("semester", sa.Integer(), nullable=False),
            sa.Column("academic_year", sa.String(length=20), nullable=True),
            sa.Column("amount", sa.Integer(), nullable=False),
            *stamps(),
            sa.UniqueConstraint("program", "residency", "year_level", "semester", name="uq_tuition_fee"),
        )
    if "enrollment_counts" not in tables:
        op.create_table(
            "enrollment_counts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("program", sa.String(length=20), nullable=True, index=True),
            sa.Column("year_level", sa.Integer(), nullable=True),
            sa.Column("students", sa.Integer(), nullable=False),
            sa.Column("as_of", sa.String(length=60), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            *stamps(),
        )


def downgrade() -> None:
    op.drop_table("enrollment_counts")
    op.drop_table("tuition_fees")
