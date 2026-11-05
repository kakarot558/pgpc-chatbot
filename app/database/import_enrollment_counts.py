"""Add or update student counts from a CSV:  python -m app.database.import_enrollment_counts data/seed/enrollment_counts.csv

Columns: program (BSCRIM, BSCS, BPA, BSMA, or empty for all), year_level (1-4, or empty for all years), students,
as_of (for example "1st Sem A.Y. 2026-2027"), note. Rows with no number in 'students' are skipped, so you can fill the
template a little at a time. An existing row for the same program and year is updated.
"""
import csv
import sys

from sqlalchemy import select

from app.database.database import SessionLocal
from app.models import EnrollmentCount
from app.services.enrollment_info import canonical_program


def import_rows(db, rows) -> dict:
    out = {"added": 0, "updated": 0, "skipped": 0}
    for row in rows:
        raw = (row.get("students") or "").strip().replace(",", "")
        if not raw.isdigit():
            out["skipped"] += 1
            continue
        prog_raw = (row.get("program") or "").strip()
        prog = canonical_program(prog_raw) if prog_raw else None
        if prog_raw and prog is None:
            out["skipped"] += 1
            continue
        year = int(row["year_level"]) if (row.get("year_level") or "").strip().isdigit() else None
        existing = db.scalar(select(EnrollmentCount).where(EnrollmentCount.program.is_(prog) if prog is None
                                                             else EnrollmentCount.program == prog,
                                                             EnrollmentCount.year_level.is_(year) if year is None
                                                             else EnrollmentCount.year_level == year))
        if existing:
            existing.students, existing.as_of = int(raw), (row.get("as_of") or "").strip() or existing.as_of
            existing.note = (row.get("note") or "").strip() or existing.note
            out["updated"] += 1
        else:
            db.add(EnrollmentCount(program=prog, year_level=year, students=int(raw),
                                   as_of=(row.get("as_of") or "").strip() or None,
                                   note=(row.get("note") or "").strip() or None))
            out["added"] += 1
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    with open(argv[1], newline="", encoding="utf-8-sig") as fh, SessionLocal() as db:
        result = import_rows(db, csv.DictReader(fh))
        db.commit()
    print("Done. " + ", ".join(f"{k}: {v}" for k, v in result.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
