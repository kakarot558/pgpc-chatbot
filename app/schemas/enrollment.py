from pydantic import Field

from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req
from typing import Annotated, Optional

TuitionFeeCreate, TuitionFeeUpdate = make_create_update("TuitionFee", {
    "program": (req(20), REQUIRED),
    "residency": (req(20), REQUIRED),
    "year_level": (Annotated[int, Field(ge=1, le=6)], REQUIRED),
    "semester": (Annotated[int, Field(ge=1, le=3)], REQUIRED),
    "academic_year": (opt(20), None),
    "amount": (Annotated[int, Field(ge=0, le=10_000_000)], REQUIRED),
})


class TuitionFeeOut(Stamped):
    program: str
    residency: str
    year_level: int
    semester: int
    academic_year: str | None
    amount: int


EnrollmentCountCreate, EnrollmentCountUpdate = make_create_update("EnrollmentCount", {
    "program": (opt(20), None),
    "year_level": (Optional[Annotated[int, Field(ge=1, le=6)]], None),
    "students": (Annotated[int, Field(ge=0, le=1_000_000)], REQUIRED),
    "as_of": (opt(60), None),
    "note": (opt(1000), None),
})


class EnrollmentCountOut(Stamped):
    program: str | None
    year_level: int | None
    students: int
    as_of: str | None
    note: str | None
