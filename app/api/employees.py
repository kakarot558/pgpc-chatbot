from app.api.crud_factory import build_crud_routers
from app.models import Employee, Office, Position
from app.schemas.employee import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.utils.validators import conflict, ensure_exists, is_duplicate


def check(db, v, exclude_id):
    if v.get("employee_number") and is_duplicate(db, Employee, {"employee_number": v["employee_number"]}, exclude_id):
        conflict("An employee with this employee number already exists.")
    same_name = {"first_name": v["first_name"], "middle_name": v.get("middle_name"), "last_name": v["last_name"]}
    if is_duplicate(db, Employee, same_name, exclude_id):
        conflict("An employee with the same name already exists.")
    ensure_exists(db, Position, v.get("position_id"), "Position")
    ensure_exists(db, Office, v.get("office_id"), "Office")


router, admin_router = build_crud_routers(
    path="employees", singular="employee", plural="employees", model=Employee,
    create_schema=EmployeeCreate, update_schema=EmployeeUpdate, out_schema=EmployeeOut,
    search_fields=("first_name", "middle_name", "last_name", "employee_number", "description"),
    order_by=(Employee.last_name, Employee.first_name), check=check)
