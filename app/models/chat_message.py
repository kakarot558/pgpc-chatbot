from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    message: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(300))
    # Added beyond the original table spec: admin chat logs must show PGPC relevance.
    pgpc_related: Mapped[bool | None] = mapped_column(Boolean)
    # Phase 9 additions (migration 9c1d5e7a2b40): what the answer was about, and whether anything was found.
    found: Mapped[bool | None] = mapped_column(Boolean)
    topic_type: Mapped[str | None] = mapped_column(String(30))     # record the answer was about (for follow-ups)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    topic_title: Mapped[str | None] = mapped_column(String(200))
    resolved_question: Mapped[str | None] = mapped_column(String(600))  # follow-up rewritten as a full question
    # Student feedback on an answer: 1 = helpful, -1 = not helpful, NULL = no vote.
    feedback: Mapped[int | None] = mapped_column(SmallInteger)
    feedback_comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
