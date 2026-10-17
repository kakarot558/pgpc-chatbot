from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

PositionCreate, PositionUpdate = make_create_update("Position", {
    "name": (req(150), REQUIRED),
    "description": (opt(5000), None),
})


class PositionOut(Stamped):
    name: str
    description: str | None
