from app.api.crud_factory import build_crud_routers
from app.models import Facility, Room
from app.schemas.facility import FacilityCreate, FacilityOut, FacilityUpdate
from app.utils.validators import conflict, count_rows, is_duplicate


def check(db, v, exclude_id):
    if is_duplicate(db, Facility, {"name": v["name"]}, exclude_id):
        conflict("A facility with this name already exists.")


def delete_check(db, obj):
    n = count_rows(db, Room, "facility_id", obj.id)
    if n:
        conflict(f"Cannot delete: {n} room(s) belong to this facility. Reassign them first.")


router, admin_router = build_crud_routers(
    path="facilities", singular="facility", plural="facilities", model=Facility,
    create_schema=FacilityCreate, update_schema=FacilityUpdate, out_schema=FacilityOut,
    search_fields=("name", "description", "location", "available_equipment"), check=check, delete_check=delete_check)
