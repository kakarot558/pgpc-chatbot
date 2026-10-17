from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

FacilityCreate, FacilityUpdate = make_create_update("Facility", {
    "name": (req(150), REQUIRED),
    "description": (opt(5000), None),
    "building": (opt(100), None),
    "location": (opt(255), None),
    "available_equipment": (opt(5000), None),
    "operating_hours": (opt(150), None),
})


class FacilityOut(Stamped):
    name: str
    description: str | None
    building: str | None
    location: str | None
    available_equipment: str | None
    operating_hours: str | None
