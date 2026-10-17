from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base
from app.models.mixins import TimestampMixin


class HandbookSection(TimestampMixin, Base):
    __tablename__ = "handbook_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    section_number: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(300), index=True)
    source_document: Mapped[str | None] = mapped_column(String(200))
    source_page: Mapped[str | None] = mapped_column(String(50))
