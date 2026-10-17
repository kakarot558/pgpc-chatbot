"""Adds the tables/columns introduced after the first version, when they are missing.

A project updated by copying new files has an OLD database; without this, the first chat after the update would fail
with "no such column: feedback". Everything here is additive (nothing is dropped) and safe to run on every start.
"""
import logging

from sqlalchemy import inspect, text

logger = logging.getLogger("pgpc.schema")

ADDED_COLUMNS = [
    ("chat_messages", "feedback", "SMALLINT"),
    ("chat_messages", "feedback_comment", "VARCHAR(500)"),
]


def ensure_schema(engine) -> list[str]:
    from app.models import QuickLink
    changed: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "quick_links" not in tables:
        QuickLink.__table__.create(engine)
        changed.append("created table quick_links")
    for table, column, sql_type in ADDED_COLUMNS:
        if table not in tables:
            continue
        if column not in {c["name"] for c in insp.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
            changed.append(f"added column {table}.{column}")
    for item in changed:
        logger.info("database updated: %s", item)
    return changed
