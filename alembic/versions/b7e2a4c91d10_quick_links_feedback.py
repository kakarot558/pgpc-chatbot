"""quick links table and answer feedback

Revision ID: b7e2a4c91d10
Revises: 9c1d5e7a2b40
Create Date: 2026-10-08 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7e2a4c91d10"
down_revision: Union[str, Sequence[str], None] = "9c1d5e7a2b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The app may already have added these at start-up (app/database/ensure_schema.py), so check first.
    insp = sa.inspect(op.get_bind())
    if "quick_links" not in insp.get_table_names():
        op.create_table(
            "quick_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("keywords", sa.Text(), nullable=False),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    existing = {c["name"] for c in insp.get_columns("chat_messages")}
    with op.batch_alter_table("chat_messages") as batch:
        if "feedback" not in existing:
            batch.add_column(sa.Column("feedback", sa.SmallInteger(), nullable=True))
        if "feedback_comment" not in existing:
            batch.add_column(sa.Column("feedback_comment", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("feedback_comment")
        batch.drop_column("feedback")
    op.drop_table("quick_links")
