"""Builds the standard list/get (public) and create/update/delete (admin) routes for one table.

Why a factory? Nine tables need almost identical routes. Writing them nine times would mean nine
copies of every bug fix, so the logic lives here once and each file (employees.py, offices.py ...)
only describes what is special about its table.
"""
import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.database.database import get_db
from app.models import User
from app.schemas.common import Page
from app.utils.validators import conflict

logger = logging.getLogger("pgpc.admin")


def build_crud_routers(*, path: str, singular: str, plural: str, model, create_schema, update_schema,
                       out_schema, search_fields=(), order_by=None, check: Callable | None = None,
                       delete_check: Callable | None = None, public_filter=None, tag: str | None = None):
    """check(db, merged_values, exclude_id)  -> raises HTTPException on duplicates / bad references.
    delete_check(db, obj)                    -> raises HTTPException if the record is still in use.
    public_filter                            -> SQL condition limiting what the public can see."""
    tag = tag or plural.title()
    public = APIRouter(prefix=f"/api/v1/{path}", tags=[tag])
    admin = APIRouter(prefix=f"/api/v1/admin/{path}", tags=[f"Admin - {tag}"], dependencies=[Depends(require_admin)])
    order = order_by if order_by is not None else (model.id,)
    not_null = {c.name for c in model.__table__.columns if not c.nullable}
    page_schema = Page[out_schema]

    def fetch_page(db: Session, skip: int, limit: int, q: str | None, only_public: bool):
        stmt = select(model)
        if only_public and public_filter is not None:
            stmt = stmt.where(public_filter)
        if q and search_fields:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(*[getattr(model, f).ilike(like) for f in search_fields]))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = db.scalars(stmt.order_by(*order).offset(skip).limit(limit)).all()
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    def fetch_one(db: Session, record_id: int, only_public: bool):
        obj = db.get(model, record_id)
        if obj is None or (only_public and public_filter is not None and
                           db.scalar(select(model.id).where(model.id == record_id, public_filter)) is None):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{singular.capitalize()} not found.")
        return obj

    def save(db: Session):
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            conflict(f"That {singular} conflicts with an existing record.")

    # ------------------------------------------------------------ public (read-only)
    @public.get("", response_model=page_schema, summary=f"List {plural}",
                description=f"Returns {plural}. Use `q` to search and `skip`/`limit` to page through results.")
    def list_public(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                    q: str | None = Query(None, max_length=100), db: Session = Depends(get_db)):
        return fetch_page(db, skip, limit, q, True)

    @public.get("/{record_id}", response_model=out_schema, summary=f"Get one {singular}",
                description=f"Returns a single {singular} by its id.")
    def get_public(record_id: int, db: Session = Depends(get_db)):
        return fetch_one(db, record_id, True)

    # If some rows are hidden from the public (e.g. inactive FAQs), admins still need to see all of them.
    if public_filter is not None:
        @admin.get("", response_model=page_schema, summary=f"List all {plural} (admin)",
                   description=f"Like the public list, but also includes {plural} hidden from the public.")
        def list_admin(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                       q: str | None = Query(None, max_length=100), db: Session = Depends(get_db)):
            return fetch_page(db, skip, limit, q, False)

        @admin.get("/{record_id}", response_model=out_schema, summary=f"Get one {singular} (admin)",
                   description=f"Returns one {singular}, including ones hidden from the public.")
        def get_admin(record_id: int, db: Session = Depends(get_db)):
            return fetch_one(db, record_id, False)

    # ------------------------------------------------------------------- admin only
    @admin.post("", response_model=out_schema, status_code=status.HTTP_201_CREATED,
                summary=f"Add a {singular}", description=f"Creates a {singular}. Duplicates are rejected with a clear message.")
    def create_item(data: create_schema, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
        values = data.model_dump()
        if check:
            check(db, values, None)
        obj = model(**values)
        db.add(obj)
        save(db)
        db.refresh(obj)
        logger.info("admin create %s id=%s by user_id=%s", path, obj.id, admin_user.id)
        return obj

    @admin.put("/{record_id}", response_model=out_schema, summary=f"Edit a {singular}",
               description="Only the fields you send are changed. Required fields cannot be set to empty.")
    def update_item(record_id: int, data: update_schema, db: Session = Depends(get_db),
                    admin_user: User = Depends(require_admin)):
        obj = fetch_one(db, record_id, False)
        changes = data.model_dump(exclude_unset=True)
        empty = [k for k, v in changes.items() if v is None and k in not_null]
        if empty:
            raise HTTPException(422, f"These fields cannot be empty: {', '.join(empty)}.")
        if check:
            merged = {k: getattr(obj, k) for k in create_schema.model_fields}
            merged.update(changes)
            check(db, merged, record_id)
        for key, value in changes.items():
            setattr(obj, key, value)
        save(db)
        db.refresh(obj)
        logger.info("admin update %s id=%s by user_id=%s", path, record_id, admin_user.id)
        return obj

    @admin.delete("/{record_id}", summary=f"Delete a {singular}",
                  description=f"Deletes a {singular}. Blocked if other records still depend on it.")
    def delete_item(record_id: int, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
        obj = fetch_one(db, record_id, False)
        if delete_check:
            delete_check(db, obj)
        db.delete(obj)
        save(db)
        logger.info("admin delete %s id=%s by user_id=%s", path, record_id, admin_user.id)
        return {"success": True, "message": f"{singular.capitalize()} deleted."}

    return public, admin
