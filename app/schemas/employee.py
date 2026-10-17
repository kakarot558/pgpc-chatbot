from app.schemas.common import REQUIRED, IdName, OptEmail, OptId, Stamped, make_create_update, opt, req

EmployeeCreate, EmployeeUpdate = make_create_update("Employee", {
    "employee_number": (opt(50), None),
    "first_name": (req(100), REQUIRED),
    "middle_name": (opt(100), None),
    "last_name": (req(100), REQUIRED),
    "position_id": (OptId, None),
    "office_id": (OptId, None),
    "email": (OptEmail, None),
    "contact_number": (opt(50), None),
    "description": (opt(5000), None),
    "status": (req(50), "active"),
})


class EmployeeOut(Stamped):
    employee_number: str | None
    first_name: str
    middle_name: str | None
    last_name: str
    position: IdName | None
    office: IdName | None
    email: str | None
    contact_number: str | None
    description: str | None
    status: str
