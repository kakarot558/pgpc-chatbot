from app.api.crud_factory import build_crud_routers
from app.models import Employee, Position
from app.schemas.position import PositionCreate, PositionOut, PositionUpdate
from app.utils.validators import conflict, count_rows, is_duplicate


def check(db, v, exclude_id):
    if is_duplicate(db, Position, {"name": v["name"]}, exclude_id):
        conflict("A position with this name already exists.")


def delete_check(db, obj):
    n = count_rows(db, Employee, "position_id", obj.id)
    if n:
        conflict(f"Cannot delete: {n} employee(s) still have this position. Reassign them first.")


router, admin_router = build_crud_routers(
    path="positions", singular="position", plural="positions", model=Position,
    create_schema=PositionCreate, update_schema=PositionUpdate, out_schema=PositionOut,
    search_fields=("name", "description"), check=check, delete_check=delete_check)
