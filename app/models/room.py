from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.models.mixins import TimestampMixin


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    # The same room number may exist in different buildings, but not twice in one.
    __table_args__ = (UniqueConstraint("room_number", "building", name="uq_room_number_building"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_number: Mapped[str] = mapped_column(String(50), index=True)
    room_name: Mapped[str | None] = mapped_column(String(150))
    building: Mapped[str | None] = mapped_column(String(100))
    floor: Mapped[str | None] = mapped_column(String(50))
    room_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id", ondelete="SET NULL"))

    facility = relationship("Facility")
