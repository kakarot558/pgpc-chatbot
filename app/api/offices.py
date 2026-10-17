from app.api.crud_factory import build_crud_routers
from app.models import Employee, Office
from app.schemas.office import OfficeCreate, OfficeOut, OfficeUpdate
from app.utils.validators import conflict, count_rows, is_duplicate


def check(db, v, exclude_id):
    if is_duplicate(db, Office, {"name": v["name"]}, exclude_id):
        conflict("An office with this name already exists.")


def delete_check(db, obj):
    n = count_rows(db, Employee, "office_id", obj.id)
    if n:
        conflict(f"Cannot delete: {n} employee(s) are assigned to this office. Reassign them first.")


router, admin_router = build_crud_routers(
    path="offices", singular="office", plural="offices", model=Office,
    create_schema=OfficeCreate, update_schema=OfficeUpdate, out_schema=OfficeOut,
    search_fields=("name", "description", "building", "room_number"), check=check, delete_check=delete_check)
