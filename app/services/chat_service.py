"""Phase 9: chat sessions and conversation memory.

    visitor message -> open (or restart) the session -> find the topic of the last answers
                    -> follow-up resolver -> Phase 8 answer pipeline -> save both messages

* A session is identified by a random token that only the visitor's browser holds. No account is needed;
  if the visitor happens to be logged in, the user id is stored too.
* A session expires SESSION_EXPIRE_MINUTES after the last message (sliding). A message sent with an expired
  token starts a fresh session with no memory of the old one.
* Memory is small on purpose: the "topic" (office, person, facility ... ) of the most recent answers, so that
  "what about its hours?" knows what "its" means. The full text of earlier answers is never re-used.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ChatMessage, ChatSession
from app.services.answer_generator import Answer, generate_answer
from app.services.followup import TOPIC_TYPES, Topic, answer_with_context
from app.utils.text_cleaner import clean_user_input

logger = logging.getLogger("pgpc.chat")   # never log message text: students may type personal details


class SessionFull(Exception):
    """The session reached MAX_SESSION_MESSAGES."""


# --------------------------------------------------------------------------- time helpers
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite gives back naive datetimes. Everything is stored in UTC, so naive means UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# --------------------------------------------------------------------------- sessions
def open_session(db: Session, token: str | None, user_id: int | None) -> tuple[ChatSession, str]:
    """Returns (session, status). status: "new" | "continued" | "restarted" (the old token had expired)."""
    settings = get_settings()
    now = utcnow()
    expires = now + timedelta(minutes=settings.session_expire_minutes)
    status = "new"
    if token:
        existing = db.scalar(select(ChatSession).where(ChatSession.session_token == token))
        if existing is not None:
            if as_utc(existing.expires_at) > now:
                existing.expires_at = expires          # sliding expiry
                if existing.user_id is None and user_id is not None:
                    existing.user_id = user_id
                return existing, "continued"
            status = "restarted"
        # an unknown token is treated as a new chat (it reveals nothing about other sessions)
    session = ChatSession(session_token=secrets.token_urlsafe(32), user_id=user_id, expires_at=expires)
    db.add(session)
    db.flush()
    return session, status


def find_active_session(db: Session, token: str | None) -> ChatSession | None:
    if not token:
        return None
    s = db.scalar(select(ChatSession).where(ChatSession.session_token == token))
    return s if s is not None and as_utc(s.expires_at) > utcnow() else None


def message_count(db: Session, session_id: int) -> int:
    return db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)) or 0


def recent_topic(db: Session, session_id: int) -> Topic | None:
    """The record the latest answers were about (skipping small talk and not-found replies)."""
    window = get_settings().followup_window
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc()).limit(window)
    ).all()
    for m in rows:
        if m.topic_type and m.topic_title:
            return Topic(m.topic_type, m.topic_id, m.topic_title)
    return None


def history(db: Session, session_id: int) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
                           .order_by(ChatMessage.id)).all())


# --------------------------------------------------------------------------- one chat turn
def _miss(text: str) -> Answer:
    return Answer(text=text, kind="not_found", intent="unknown", intent_confidence=0.0, found=False,
                  confidence="none", pgpc_related=True)


def _topic_of(answer: Answer) -> Topic | None:
    """What this answer was about. A list, a miss, small talk, or an FAQ/history answer has no usable topic, so
    the previous topic stays available for the next follow-up."""
    if answer.kind == "answer" and answer.found and answer.topic_hint:
        return Topic("handbook", None, answer.topic_hint)       # "haircut": a follow-up asks about THIS, not a section
    if answer.kind == "answer" and answer.found and answer.sources:
        s = answer.sources[0]
        if s["type"] in TOPIC_TYPES and s.get("title"):
            return Topic(s["type"], s.get("id"), s["title"])
    return None


def answer_message(db: Session, message: str, topic: Topic | None) -> tuple[Answer, str | None]:
    """Phase 8 pipeline plus follow-up handling. Returns (answer, interpreted_as)."""
    from app.services.intent_classifier import get_intent_classifier   # loads the model on first use
    classifier = get_intent_classifier()
    return answer_with_context(
        message, topic,
        answer_fn=lambda q: generate_answer(db, q),
        classify=lambda q: classifier.predict(q).intent,
        miss_fn=_miss,
    )


def process_message(db: Session, message: str, token: str | None, user_id: int | None) -> dict:
    settings = get_settings()
    message = clean_user_input(message)[: settings.max_question_chars]
    session, status = open_session(db, token, user_id)

    if message_count(db, session.id) >= settings.max_session_messages:
        db.rollback()
        raise SessionFull()

    topic = recent_topic(db, session.id)
    answer, interpreted = answer_message(db, message, topic)
    if interpreted is None and answer.understood_as:
        interpreted = answer.understood_as              # typos / slang repaired by the input reader
    new_topic = _topic_of(answer)

    db.add(ChatMessage(session_id=session.id, role="user", message=message, intent=answer.intent,
                       confidence=answer.intent_confidence, pgpc_related=answer.pgpc_related, found=answer.found,
                       resolved_question=interpreted[:600] if interpreted else None))
    source_text = "; ".join(f"{s['source']}" for s in answer.sources)[:300] or None
    reply = ChatMessage(session_id=session.id, role="assistant", message=answer.text, intent=answer.intent,
                        confidence=answer.intent_confidence, pgpc_related=answer.pgpc_related, found=answer.found,
                        source=source_text,
                        topic_type=new_topic.type if new_topic else None,
                        topic_id=new_topic.id if new_topic else None,
                        topic_title=new_topic.title[:200] if new_topic else None)
    db.add(reply)
    db.commit()
    db.refresh(session)
    db.refresh(reply)
    logger.info("chat ok session_id=%s status=%s kind=%s followup=%s", session.id, status, answer.kind,
                bool(interpreted))

    remaining = max(0, int((as_utc(session.expires_at) - utcnow()).total_seconds()))
    return {
        "success": True,
        "session_token": session.session_token,
        "session": {"status": status, "expires_at": as_utc(session.expires_at).isoformat(),
                    "expires_in_seconds": remaining},
        "message_id": reply.id,
        "question": message,
        "follow_up": {"resolved": interpreted is not None, "interpreted_as": interpreted},
        **answer.as_dict(),
    }


# --------------------------------------------------------------------------- clean-up
def delete_sessions(db: Session, session_ids: list[int]) -> int:
    """Deletes sessions and their messages. Messages are removed explicitly so it works whether or not the
    database enforces ON DELETE CASCADE."""
    if not session_ids:
        return 0
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    result = db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))
    db.commit()
    return result.rowcount or 0


def purge_expired(db: Session, older_than_days: int | None = None) -> int:
    """Removes sessions that expired more than `older_than_days` ago (default CHAT_RETENTION_DAYS)."""
    days = get_settings().chat_retention_days if older_than_days is None else older_than_days
    cutoff = utcnow() - timedelta(days=days)
    ids = list(db.scalars(select(ChatSession.id).where(ChatSession.expires_at < cutoff)).all())
    return delete_sessions(db, ids)
