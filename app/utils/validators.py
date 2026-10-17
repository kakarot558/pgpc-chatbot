"""Duplicate and reference checks shared by the admin routes."""
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def is_duplicate(db: Session, model, values: dict, exclude_id: int | None = None) -> bool:
    """True if another row has the same values (text compared case-insensitively, None matches NULL)."""
    stmt = select(model.id)
    for column, value in values.items():
        col = getattr(model, column)
        if value is None:
            stmt = stmt.where(col.is_(None))
        elif isinstance(value, str):
            stmt = stmt.where(func.lower(col) == value.strip().lower())
        else:
            stmt = stmt.where(col == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.scalar(stmt.limit(1)) is not None


def conflict(message: str):
    raise HTTPException(status.HTTP_409_CONFLICT, message)


def bad_reference(message: str):
    raise HTTPException(422, message)


def ensure_exists(db: Session, model, record_id: int | None, label: str):
    """Reject a foreign key that points to a record that does not exist."""
    if record_id is not None and db.get(model, record_id) is None:
        bad_reference(f"{label} with id {record_id} does not exist.")


def count_rows(db: Session, model, column: str, value: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(getattr(model, column) == value)) or 0
