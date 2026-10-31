"""Load the personnel titles, office locations and rooms:  python -m app.database.apply_campus_data
Safe to run again. It fills empty fields only and never replaces what the admin typed."""
import sys

from app.database.campus_data import apply
from app.database.database import SessionLocal


def main() -> int:
    with SessionLocal() as db:
        counts = apply(db)
        db.commit()
    print("Done. " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
