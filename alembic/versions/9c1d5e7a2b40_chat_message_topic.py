"""chat messages: topic, found and resolved question (Phase 9)

Revision ID: 9c1d5e7a2b40
Revises: 4919060de552
Create Date: 2026-10-02 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9c1d5e7a2b40"
down_revision: Union[str, Sequence[str], None] = "4919060de552"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode: SQLite cannot alter tables in place, so Alembic rebuilds the table safely.
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("found", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("topic_type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("topic_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("topic_title", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("resolved_question", sa.String(length=600), nullable=True))
    op.create_index(op.f("ix_chat_sessions_expires_at"), "chat_sessions", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_sessions_expires_at"), table_name="chat_sessions")
    with op.batch_alter_table("chat_messages") as batch:
        for col in ("resolved_question", "topic_title", "topic_id", "topic_type", "found"):
            batch.drop_column(col)
