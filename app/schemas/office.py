from app.schemas.common import REQUIRED, OptEmail, Stamped, make_create_update, opt, req

OfficeCreate, OfficeUpdate = make_create_update("Office", {
    "name": (req(150), REQUIRED),
    "description": (opt(5000), None),
    "building": (opt(100), None),
    "floor": (opt(50), None),
    "room_number": (opt(50), None),
    "contact_number": (opt(50), None),
    "email": (OptEmail, None),
})


class OfficeOut(Stamped):
    name: str
    description: str | None
    building: str | None
    floor: str | None
    room_number: str | None
    contact_number: str | None
    email: str | None
