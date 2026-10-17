from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base
from app.models.mixins import TimestampMixin


class LibraryBook(TimestampMixin, Base):
    """Optional module."""
    __tablename__ = "library_books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    author: Mapped[str | None] = mapped_column(String(200))
    isbn: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(100))
    publisher: Mapped[str | None] = mapped_column(String(200))
    year: Mapped[str | None] = mapped_column(String(10))
    availability: Mapped[str | None] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(150))
