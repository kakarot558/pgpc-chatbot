from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base
from app.models.mixins import TimestampMixin


class TuitionFee(TimestampMixin, Base):
    """One amount from the PGPC fee table: program + Garciano / Non-Garciano + year level + semester."""
    __tablename__ = "tuition_fees"
    __table_args__ = (UniqueConstraint("program", "residency", "year_level", "semester", name="uq_tuition_fee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    program: Mapped[str] = mapped_column(String(20), index=True)           # BSCRIM, BSCS, BPA, BSMA
    residency: Mapped[str] = mapped_column(String(20))                      # "Garciano" or "Non-Garciano"
    year_level: Mapped[int] = mapped_column(Integer)                        # 1 to 4
    semester: Mapped[int] = mapped_column(Integer)                          # 1 or 2
    academic_year: Mapped[str | None] = mapped_column(String(20))           # as printed in the table, e.g. "2025-2026"
    amount: Mapped[int] = mapped_column(Integer)                            # pesos


class EnrollmentCount(TimestampMixin, Base):
    """Number of enrolled students, entered by the admin (never invented). Leave program or year empty for a total."""
    __tablename__ = "enrollment_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    program: Mapped[str | None] = mapped_column(String(20), index=True)     # None = all programs
    year_level: Mapped[int | None] = mapped_column(Integer)                 # None = all year levels
    students: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[str | None] = mapped_column(String(60))                   # e.g. "1st Sem A.Y. 2026-2027"
    note: Mapped[str | None] = mapped_column(Text)
