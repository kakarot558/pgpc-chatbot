from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base
from app.models.mixins import TimestampMixin


class QuickLink(TimestampMixin, Base):
    """An official link the chatbot gives when a question contains certain words. Edited in the admin dashboard."""
    __tablename__ = "quick_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # Phrases separated by commas or new lines. A question matches a phrase when it contains ALL of its words.
    keywords: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500))
    message: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
