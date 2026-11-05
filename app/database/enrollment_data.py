"""Loads the fee table and the enrollment procedures the Registrar gave (Procedures during Enrollment 2026).

Safe to run again: it only adds what is missing and never replaces what the admin edited.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FAQ, TuitionFee
from app.services import enrollment_info as ei


def apply(db: Session) -> dict:
    out = {"fees_added": 0, "procedures_added": 0}
    have = {(f.program, f.residency, f.year_level, f.semester) for f in db.scalars(select(TuitionFee))}
    for r in ei.default_fee_rows():
        if (r["program"], r["residency"], r["year_level"], r["semester"]) not in have:
            db.add(TuitionFee(**r))
            out["fees_added"] += 1
    existing = list(db.scalars(select(FAQ).where(FAQ.category == ei.PROCEDURE_CATEGORY)))
    has_sem2 = any("2nd sem" in (f.keywords or "").lower() for f in existing)
    if not any("incoming" in (f.keywords or "").lower() for f in existing):
        db.add(FAQ(question=ei.NEW_QUESTION, answer=ei.NEW_ANSWER, category=ei.PROCEDURE_CATEGORY,
                   keywords="incoming first year freshman new student enrollment procedure steps",
                   source=ei.PROCEDURE_SOURCE, is_active=True))
        out["procedures_added"] += 1
    if not has_sem2:
        db.add(FAQ(question=ei.SEM2_QUESTION, answer=ei.SEM2_ANSWER, category=ei.PROCEDURE_CATEGORY,
                   keywords="2nd sem second semester continuing returning old student enrollment procedure steps",
                   source=ei.PROCEDURE_SOURCE, is_active=True))
        out["procedures_added"] += 1
    return out
