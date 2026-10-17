"""Phase 9: chat sessions (public) and chat logs (admin only)."""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_optional_user, require_admin
from app.database.database import get_db
from app.models import ChatMessage, ChatSession, User
from app.schemas.chat import ChatRequest, FeedbackRequest
from app.services import chat_service as chat
from app.services.intent_classifier import OUT_OF_SCOPE_INTENT, SMALL_TALK_INTENTS

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])
admin_router = APIRouter(prefix="/api/v1/admin/chat", tags=["Admin - Chat logs"],
                         dependencies=[Depends(require_admin)])

TOKEN_HEADER = Header(None, alias="X-Session-Token", max_length=64,
                      description="The session_token returned by POST /api/v1/chat")


# =========================================================================== public
@router.post("", summary="Send a message to PGPC SmartGuide",
             description="Answers a question and remembers the conversation, so simple follow-ups such as "
                         "\"what about its hours?\" work. Leave session_token out to start a new chat, then send the "
                         "returned token with every later message. A session expires after "
                         "SESSION_EXPIRE_MINUTES without messages; sending an expired token starts a new chat "
                         "(session.status = \"restarted\"). No account is needed.")
def send_message(data: ChatRequest, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    try:
        return chat.process_message(db, data.message, data.session_token, user.id if user else None)
    except chat.SessionFull:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "This conversation has reached its message limit. Please start a new chat.")


@router.post("/feedback", summary="Mark an answer as helpful or not helpful",
             description="The student's thumbs up / thumbs down. Send the session token in the X-Session-Token header; "
                         "only answers of that chat can be rated. value=clear removes the vote.")
def rate_answer(data: FeedbackRequest, token: str | None = TOKEN_HEADER, db: Session = Depends(get_db)):
    session = chat.find_active_session(db, token)
    if session is None:
        raise HTTPException(404, "This chat has expired. Please ask your question again.")
    message = db.get(ChatMessage, data.message_id)
    if message is None or message.session_id != session.id or message.role != "assistant":
        raise HTTPException(404, "Answer not found in this chat.")
    message.feedback = {"up": 1, "down": -1, "clear": None}[data.value]
    message.feedback_comment = data.comment if data.value == "down" else None
    db.commit()
    return {"success": True, "message_id": message.id, "feedback": data.value if data.value != "clear" else None}


@router.get("/history", summary="Messages of the current chat",
            description="Send the session token in the X-Session-Token header. An expired or unknown token "
                        "returns an empty history.")
def chat_history(token: str | None = TOKEN_HEADER, db: Session = Depends(get_db)):
    session = chat.find_active_session(db, token)
    if session is None:
        return {"success": True, "active": False, "messages": []}
    return {
        "success": True, "active": True,
        "expires_at": chat.as_utc(session.expires_at).isoformat(),
        "messages": [{"id": m.id, "role": m.role, "message": m.message, "source": m.source,
                      "created_at": chat.as_utc(m.created_at).isoformat()} for m in chat.history(db, session.id)],
    }


@router.delete("/session", summary="Clear this chat",
               description="Deletes the session and its messages (the \"New chat\" button). Always succeeds, "
                           "even when the token is unknown or already expired.")
def clear_chat(token: str | None = TOKEN_HEADER, db: Session = Depends(get_db)):
    if token:
        session = db.scalar(select(ChatSession).where(ChatSession.session_token == token))
        if session is not None:
            chat.delete_sessions(db, [session.id])
    return {"success": True, "message": "Chat cleared."}


# =========================================================================== admin
def _iso(value: datetime | None) -> str | None:
    return chat.as_utc(value).isoformat() if value else None


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


@admin_router.get("/sessions", summary="List chat sessions",
                  description="Newest first. A session is \"expired\" once its expires_at has passed.")
def list_sessions(active: bool | None = Query(None, description="true = still open, false = expired"),
                  skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db)):
    now = chat.utcnow()
    count = func.count(ChatMessage.id)
    stmt = (select(ChatSession, count.label("n"), func.max(ChatMessage.created_at).label("last"))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id).group_by(ChatSession.id))
    total_stmt = select(func.count(ChatSession.id))
    if active is True:
        stmt, total_stmt = stmt.where(ChatSession.expires_at > now), total_stmt.where(ChatSession.expires_at > now)
    elif active is False:
        stmt, total_stmt = stmt.where(ChatSession.expires_at <= now), total_stmt.where(ChatSession.expires_at <= now)
    rows = db.execute(stmt.order_by(ChatSession.id.desc()).offset(skip).limit(limit)).all()
    return {
        "success": True, "total": db.scalar(total_stmt) or 0, "skip": skip, "limit": limit,
        "items": [{"id": s.id, "user_id": s.user_id, "created_at": _iso(s.created_at),
                   "expires_at": _iso(s.expires_at), "expired": chat.as_utc(s.expires_at) <= now,
                   "message_count": n, "last_activity": _iso(last)} for s, n, last in rows],
    }


@admin_router.get("/sessions/{session_id}", summary="Read one conversation")
def read_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "Chat session not found.")
    return {
        "success": True,
        "session": {"id": s.id, "user_id": s.user_id, "created_at": _iso(s.created_at),
                    "expires_at": _iso(s.expires_at), "expired": chat.as_utc(s.expires_at) <= chat.utcnow()},
        "messages": [{"id": m.id, "role": m.role, "message": m.message, "intent": m.intent,
                      "confidence": m.confidence, "pgpc_related": m.pgpc_related, "found": m.found,
                      "source": m.source, "interpreted_as": m.resolved_question,
                      "created_at": _iso(m.created_at)} for m in chat.history(db, s.id)],
    }


@admin_router.delete("/sessions/{session_id}", summary="Delete one conversation")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    if db.get(ChatSession, session_id) is None:
        raise HTTPException(404, "Chat session not found.")
    chat.delete_sessions(db, [session_id])
    return {"success": True, "message": "Chat session deleted."}


@admin_router.delete("/expired-sessions", summary="Purge old expired conversations",
                     description="Deletes sessions that expired more than older_than_days ago "
                                 "(default: CHAT_RETENTION_DAYS). Use 0 to delete every expired session.")
def purge_expired(older_than_days: int | None = Query(None, ge=0, le=3650), db: Session = Depends(get_db)):
    return {"success": True, "deleted": chat.purge_expired(db, older_than_days)}


@admin_router.get("/logs", summary="Chat logs: every question with its answer",
                  description="One row per visitor question. Filter by PGPC relevance, intent, found/not found, "
                              "words in the question, or date. found=false shows what students asked that the "
                              "knowledge base could not answer.")
def chat_logs(pgpc_related: bool | None = None, intent: str | None = Query(None, max_length=50),
              found: bool | None = None, q: str | None = Query(None, max_length=100),
              date_from: date | None = None, date_to: date | None = None,
              skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    where = [ChatMessage.role == "user"]
    if pgpc_related is not None:
        where.append(ChatMessage.pgpc_related.is_(pgpc_related))
    if intent:
        where.append(ChatMessage.intent == intent)
    if found is not None:
        where.append(ChatMessage.found.is_(found))
    if q and q.strip():
        where.append(or_(ChatMessage.message.icontains(q.strip(), autoescape=True),
                         ChatMessage.resolved_question.icontains(q.strip(), autoescape=True)))
    if date_from:
        where.append(ChatMessage.created_at >= _day_start(date_from))
    if date_to:
        where.append(ChatMessage.created_at < _day_start(date_to) + timedelta(days=1))
    total = db.scalar(select(func.count(ChatMessage.id)).where(*where)) or 0
    rows = db.scalars(select(ChatMessage).where(*where).order_by(ChatMessage.id.desc())
                      .offset(skip).limit(limit)).all()
    items = []
    for m in rows:
        reply = db.scalar(select(ChatMessage).where(ChatMessage.session_id == m.session_id,
                                                    ChatMessage.role == "assistant", ChatMessage.id > m.id)
                          .order_by(ChatMessage.id).limit(1))
        items.append({"id": m.id, "session_id": m.session_id, "asked_at": _iso(m.created_at),
                      "question": m.message, "interpreted_as": m.resolved_question, "intent": m.intent,
                      "intent_confidence": m.confidence, "pgpc_related": m.pgpc_related, "found": m.found,
                      "answer": reply.message if reply else None, "source": reply.source if reply else None})
    return {"success": True, "total": total, "skip": skip, "limit": limit, "items": items}


@admin_router.get("/feedback", summary="Answers students rated",
                  description="Newest first, with the question that was asked. value=down shows the answers students "
                              "found unhelpful: the best list of what to fix next.")
def feedback_list(value: str | None = Query(None, pattern="^(up|down)$"),
                  skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    where = [ChatMessage.role == "assistant", ChatMessage.feedback.is_not(None)]
    if value:
        where.append(ChatMessage.feedback == (1 if value == "up" else -1))
    total = db.scalar(select(func.count(ChatMessage.id)).where(*where)) or 0
    rows = db.scalars(select(ChatMessage).where(*where).order_by(ChatMessage.id.desc()).offset(skip).limit(limit)).all()
    items = []
    for m in rows:
        asked = db.scalar(select(ChatMessage).where(ChatMessage.session_id == m.session_id, ChatMessage.role == "user",
                                                    ChatMessage.id < m.id).order_by(ChatMessage.id.desc()).limit(1))
        items.append({"id": m.id, "session_id": m.session_id, "feedback": "up" if m.feedback == 1 else "down",
                      "comment": m.feedback_comment, "question": asked.message if asked else None,
                      "interpreted_as": asked.resolved_question if asked else None, "answer": m.message,
                      "source": m.source, "created_at": _iso(m.created_at)})
    return {"success": True, "total": total, "skip": skip, "limit": limit, "items": items}


@admin_router.get("/unanswered", summary="Questions the chatbot could not answer, grouped",
                  description="The same question asked several times is one row with a count. Work through the top of "
                              "this list each week: add a FAQ, a quick link, or fix the handbook text. Small talk and "
                              "off-topic questions are left out.")
def unanswered(limit: int = Query(30, ge=1, le=100), min_count: int = Query(1, ge=1, le=1000),
               db: Session = Depends(get_db)):
    skip_intents = list(SMALL_TALK_INTENTS | {OUT_OF_SCOPE_INTENT})
    rows = db.scalars(select(ChatMessage).where(ChatMessage.role == "user", ChatMessage.found.is_(False),
                                                ChatMessage.intent.notin_(skip_intents))
                      .order_by(ChatMessage.id.desc()).limit(2000)).all()
    groups: dict[str, dict] = {}
    for m in rows:
        text = (m.resolved_question or m.message or "").strip()
        key = " ".join(text.lower().split()).rstrip("?!. ")
        if not key:
            continue
        g = groups.setdefault(key, {"question": text, "count": 0, "last_asked": _iso(m.created_at), "intent": m.intent})
        g["count"] += 1
    items = sorted((g for g in groups.values() if g["count"] >= min_count), key=lambda g: (-g["count"], g["question"]))
    return {"success": True, "total": len(items), "items": items[:limit]}


@admin_router.get("/summary", summary="Chat usage summary",
                  description="Counts for the dashboard. \"unanswered\" are PGPC questions the knowledge base could "
                              "not answer (small talk and off-topic questions are counted separately).")
def chat_summary(db: Session = Depends(get_db)):
    now = chat.utcnow()
    sessions = db.scalar(select(func.count(ChatSession.id))) or 0
    active = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.expires_at > now)) or 0
    by_intent = db.execute(select(ChatMessage.intent, ChatMessage.found, func.count(ChatMessage.id))
                           .where(ChatMessage.role == "user").group_by(ChatMessage.intent, ChatMessage.found)).all()
    answered = small_talk = off_topic = unanswered = 0
    intents: dict[str, int] = {}
    for name, found, n in by_intent:
        intents[name or "unknown"] = intents.get(name or "unknown", 0) + n
        if found:
            answered += n
        elif name in SMALL_TALK_INTENTS:
            small_talk += n
        elif name == OUT_OF_SCOPE_INTENT:
            off_topic += n
        else:
            unanswered += n
    recent = db.scalars(select(ChatMessage).where(ChatMessage.role == "user", ChatMessage.found.is_(False),
                                                  ChatMessage.intent.notin_(list(SMALL_TALK_INTENTS | {OUT_OF_SCOPE_INTENT})))
                        .order_by(ChatMessage.id.desc()).limit(10)).all()
    helpful = db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.feedback == 1)) or 0
    not_helpful = db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.feedback == -1)) or 0
    return {
        "success": True, "sessions": sessions, "active_sessions": active,
        "helpful": helpful, "not_helpful": not_helpful,
        "questions": sum(intents.values()), "answered": answered, "small_talk": small_talk,
        "out_of_scope": off_topic, "unanswered": unanswered,
        "top_intents": sorted(({"intent": k, "count": v} for k, v in intents.items()),
                              key=lambda r: -r["count"])[:10],
        "recent_unanswered": [{"id": m.id, "question": m.message, "asked_at": _iso(m.created_at)} for m in recent],
    }
