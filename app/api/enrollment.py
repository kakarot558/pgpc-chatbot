from app.api.crud_factory import build_crud_routers
from app.models import EnrollmentCount, TuitionFee
from app.schemas.enrollment import (EnrollmentCountCreate, EnrollmentCountOut, EnrollmentCountUpdate,
                                    TuitionFeeCreate, TuitionFeeOut, TuitionFeeUpdate)
from app.services.enrollment_info import canonical_program
from app.utils.validators import conflict


def check_fee(db, v, exclude_id):
    from fastapi import HTTPException
    prog = canonical_program(v["program"])
    if prog is None:
        raise HTTPException(422, "Program must be one of BSCRIM, BSCS, BPA or BSMA.")
    v["program"] = prog
    if v["residency"].strip().lower().replace(" ", "-") not in {"garciano", "non-garciano"}:
        raise HTTPException(422, 'Residency must be "Garciano" or "Non-Garciano".')
    v["residency"] = "Non-Garciano" if v["residency"].lower().startswith("non") else "Garciano"
    from sqlalchemy import select
    q = select(TuitionFee.id).where(TuitionFee.program == prog, TuitionFee.residency == v["residency"],
                                    TuitionFee.year_level == v["year_level"], TuitionFee.semester == v["semester"])
    if exclude_id:
        q = q.where(TuitionFee.id != exclude_id)
    if db.scalar(q) is not None:
        conflict("That fee already exists. Edit it instead of adding it again.")


def check_count(db, v, exclude_id):
    from fastapi import HTTPException
    if v.get("program"):
        prog = canonical_program(v["program"])
        if prog is None:
            raise HTTPException(422, "Program must be one of BSCRIM, BSCS, BPA or BSMA (or empty for all programs).")
        v["program"] = prog


fee_router, fee_admin_router = build_crud_routers(
    path="tuition-fees", singular="tuition fee", plural="tuition fees", model=TuitionFee,
    create_schema=TuitionFeeCreate, update_schema=TuitionFeeUpdate, out_schema=TuitionFeeOut,
    search_fields=("program", "residency", "academic_year"), check=check_fee, tag="Tuition fees",
    order_by=(TuitionFee.program, TuitionFee.year_level, TuitionFee.semester, TuitionFee.residency))

count_router, count_admin_router = build_crud_routers(
    path="enrollment-counts", singular="enrollment count", plural="enrollment counts", model=EnrollmentCount,
    create_schema=EnrollmentCountCreate, update_schema=EnrollmentCountUpdate, out_schema=EnrollmentCountOut,
    search_fields=("program", "as_of"), check=check_count, tag="Enrollment counts")
