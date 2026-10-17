from app.schemas.common import REQUIRED, OptId, Stamped, make_create_update, opt, req

RoomCreate, RoomUpdate = make_create_update("Room", {
    "room_number": (req(50), REQUIRED),
    "room_name": (opt(150), None),
    "building": (opt(100), None),
    "floor": (opt(50), None),
    "room_type": (opt(100), None),
    "description": (opt(5000), None),
    "facility_id": (OptId, None),
})


class RoomOut(Stamped):
    room_number: str
    room_name: str | None
    building: str | None
    floor: str | None
    room_type: str | None
    description: str | None
    facility_id: int | None
