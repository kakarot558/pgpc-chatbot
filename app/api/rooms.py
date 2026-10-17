from app.api.crud_factory import build_crud_routers
from app.models import Facility, Room
from app.schemas.room import RoomCreate, RoomOut, RoomUpdate
from app.utils.validators import conflict, ensure_exists, is_duplicate


def check(db, v, exclude_id):
    # The same room number is fine in two buildings, but not twice in one building.
    if is_duplicate(db, Room, {"room_number": v["room_number"], "building": v.get("building")}, exclude_id):
        conflict("A room with this number already exists in that building.")
    ensure_exists(db, Facility, v.get("facility_id"), "Facility")


router, admin_router = build_crud_routers(
    path="rooms", singular="room", plural="rooms", model=Room,
    create_schema=RoomCreate, update_schema=RoomUpdate, out_schema=RoomOut,
    search_fields=("room_number", "room_name", "building", "room_type", "description"), check=check)
