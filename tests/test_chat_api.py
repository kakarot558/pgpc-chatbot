"""Phase 9 tests: chat sessions, follow-ups, expiry, limits and admin chat logs (in-memory SQLite)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.database.database import Base, get_db
from app.main import app
from app.models import ChatMessage, ChatSession, Office, User
from app.services import chat_service
from app.services import retrieval as rv


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    rv.clear_index_cache()
    yield sessionmaker(bind=engine)
    rv.clear_index_cache()


@pytest.fixture()
def client(session_factory):
    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    with session_factory() as s:
        s.add(User(username="boss", email="boss@x.com", password_hash=hash_password("AdminPass1"), role="admin"))
        s.add(User(username="stud", email="stud@x.com", password_hash=hash_password("StudPass12"), role="user"))
        s.commit()

    def login(name, pw):
        r = c.post("/api/v1/auth/login", data={"username": name, "password": pw})
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    c.admin, c.user = login("boss", "AdminPass1"), login("stud", "StudPass12")
    yield c
    app.dependency_overrides.clear()


def say(client, message, token=None, headers=None):
    body = {"message": message}
    if token:
        body["session_token"] = token
    res = client.post("/api/v1/chat", json=body, headers=headers or {})
    assert res.status_code == 200, res.text
    return res.json()


def add_registrar(session_factory):
    with session_factory() as s:
        s.add(Office(name="Registrar Office", building="Main Building", floor="1", room_number="102",
                     contact_number="043-111-2222"))
        s.commit()


# ------------------------------------------------------------------ sessions
def test_first_message_starts_a_session(client):
    body = say(client, "hello")
    assert body["success"] and body["kind"] == "small_talk"
    assert len(body["session_token"]) >= 32 and body["session"]["status"] == "new"
    assert 0 < body["session"]["expires_in_seconds"] <= get_settings().session_expire_minutes * 60


def test_token_continues_the_same_session_and_history_is_kept(client):
    first = say(client, "hello")
    second = say(client, "thanks", first["session_token"])
    assert second["session_token"] == first["session_token"] and second["session"]["status"] == "continued"
    hist = client.get("/api/v1/chat/history", headers={"X-Session-Token": first["session_token"]}).json()
    assert hist["active"] and [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]
    assert hist["messages"][0]["message"] == "hello"


def test_unknown_token_starts_a_new_session(client):
    body = say(client, "hello", "not-a-real-token")
    assert body["session"]["status"] == "new" and body["session_token"] != "not-a-real-token"


def test_blank_message_is_rejected(client):
    assert client.post("/api/v1/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/v1/chat", json={}).status_code == 422


def test_logged_in_user_id_is_stored_but_not_required(client, session_factory):
    anon = say(client, "hello")
    mine = say(client, "hello", headers=client.user)
    bad = say(client, "hello", headers={"Authorization": "Bearer garbage"})   # a bad token is just anonymous
    with session_factory() as s:
        by_token = {x.session_token: x.user_id for x in s.scalars(select(ChatSession))}
    assert by_token[anon["session_token"]] is None and by_token[bad["session_token"]] is None
    assert by_token[mine["session_token"]] is not None


# ------------------------------------------------------------------ expiry
def test_expired_session_restarts_without_memory(client, session_factory):
    add_registrar(session_factory)
    first = say(client, "where is the registrar office")
    with session_factory() as s:                     # make the session expire an hour ago
        sess = s.scalar(select(ChatSession))
        sess.expires_at = chat_service.utcnow() - timedelta(minutes=1)
        s.commit()
    hist = client.get("/api/v1/chat/history", headers={"X-Session-Token": first["session_token"]}).json()
    assert hist["active"] is False and hist["messages"] == []
    again = say(client, "what about its hours", first["session_token"])
    assert again["session"]["status"] == "restarted" and again["session_token"] != first["session_token"]
    assert again["follow_up"]["resolved"] is False         # the old topic was forgotten


def test_each_message_extends_the_session(client, session_factory):
    first = say(client, "hello")
    with session_factory() as s:
        sess = s.scalar(select(ChatSession))
        sess.expires_at = chat_service.utcnow() + timedelta(minutes=2)
        s.commit()
    again = say(client, "thanks", first["session_token"])
    assert again["session"]["expires_in_seconds"] > 600


def test_message_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_session_messages", 2)
    first = say(client, "hello")                             # 2 messages stored
    res = client.post("/api/v1/chat", json={"message": "thanks", "session_token": first["session_token"]})
    assert res.status_code == 429


def test_clear_chat_deletes_the_session_and_messages(client, session_factory):
    first = say(client, "hello")
    res = client.delete("/api/v1/chat/session", headers={"X-Session-Token": first["session_token"]})
    assert res.status_code == 200
    with session_factory() as s:
        assert s.scalars(select(ChatSession)).all() == [] and s.scalars(select(ChatMessage)).all() == []
    assert client.delete("/api/v1/chat/session").status_code == 200     # idempotent


# ------------------------------------------------------------------ follow-ups
def test_follow_up_uses_the_previous_topic(client, session_factory):
    add_registrar(session_factory)
    first = say(client, "where is the registrar office")
    assert first["found"] and first["sources"][0]["title"] == "Registrar Office"
    follow = say(client, "what is its contact number", first["session_token"])
    assert follow["follow_up"]["resolved"] and "Registrar Office" in follow["follow_up"]["interpreted_as"]
    assert follow["found"] and "043-111-2222" in follow["answer"]


def test_follow_up_without_a_topic_is_not_guessed(client):
    body = say(client, "what about its hours")
    assert body["follow_up"] == {"resolved": False, "interpreted_as": None}
    assert not body["found"]


def test_follow_up_about_a_missing_detail_says_so(client, session_factory):
    add_registrar(session_factory)
    first = say(client, "where is the registrar office")
    follow = say(client, "what about its hours?", first["session_token"])
    assert not follow["answer"].count("[ADMIN")
    assert "Registrar Office" in follow["answer"]        # still about the registrar, never another record


def test_small_talk_between_questions_keeps_the_topic(client, session_factory):
    add_registrar(session_factory)
    first = say(client, "where is the registrar office")
    token = first["session_token"]
    say(client, "thanks", token)
    follow = say(client, "what is its contact number", token)
    assert follow["follow_up"]["resolved"] and "043-111-2222" in follow["answer"]


# ------------------------------------------------------------------ admin chat logs
def test_admin_chat_routes_need_an_admin(client):
    for path in ("/sessions", "/logs", "/summary"):
        url = "/api/v1/admin/chat" + path
        assert client.get(url).status_code == 401
        assert client.get(url, headers=client.user).status_code == 403
        assert client.get(url, headers=client.admin).status_code == 200


def test_admin_sees_questions_answers_and_filters(client, session_factory):
    add_registrar(session_factory)
    token = say(client, "where is the registrar office")["session_token"]
    say(client, "what is its contact number", token)
    say(client, "what is the capital of France")
    say(client, "hello")
    admin = client.admin

    logs = client.get("/api/v1/admin/chat/logs", headers=admin).json()
    assert logs["total"] == 4 and logs["items"][0]["question"] == "hello"
    by_q = {i["question"]: i for i in logs["items"]}
    assert by_q["what is its contact number"]["interpreted_as"]
    assert "043-111-2222" in by_q["what is its contact number"]["answer"]
    assert by_q["what is the capital of France"]["pgpc_related"] is False

    off = client.get("/api/v1/admin/chat/logs", params={"pgpc_related": False}, headers=admin).json()
    assert [i["question"] for i in off["items"]] == ["what is the capital of France"]
    hits = client.get("/api/v1/admin/chat/logs", params={"q": "registrar"}, headers=admin).json()
    assert hits["total"] == 2            # the question and its rewritten follow-up both mention the registrar
    page = client.get("/api/v1/admin/chat/logs", params={"limit": 1, "skip": 1}, headers=admin).json()
    assert page["total"] == 4 and len(page["items"]) == 1

    summary = client.get("/api/v1/admin/chat/summary", headers=admin).json()
    assert summary["sessions"] == 3 and summary["questions"] == 4 and summary["answered"] >= 2
    assert summary["small_talk"] == 1 and summary["out_of_scope"] >= 1


def test_admin_reads_and_deletes_a_session(client):
    token = say(client, "hello")["session_token"]
    sessions = client.get("/api/v1/admin/chat/sessions", headers=client.admin).json()
    sid = sessions["items"][0]["id"]
    assert sessions["items"][0]["message_count"] == 2 and sessions["items"][0]["expired"] is False
    detail = client.get(f"/api/v1/admin/chat/sessions/{sid}", headers=client.admin).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert client.delete(f"/api/v1/admin/chat/sessions/{sid}", headers=client.admin).status_code == 200
    assert client.get(f"/api/v1/admin/chat/sessions/{sid}", headers=client.admin).status_code == 404
    assert client.delete(f"/api/v1/admin/chat/sessions/{sid}", headers=client.admin).status_code == 404


def test_purge_removes_only_old_expired_sessions(client, session_factory):
    say(client, "hello")                 # stays active
    say(client, "hello")                 # will be expired long ago
    say(client, "hello")                 # expired a minute ago (inside the retention period)
    with session_factory() as s:
        a, b, c = s.scalars(select(ChatSession).order_by(ChatSession.id)).all()
        b.expires_at = chat_service.utcnow() - timedelta(days=60)
        c.expires_at = chat_service.utcnow() - timedelta(minutes=1)
        s.commit()
    res = client.delete("/api/v1/admin/chat/expired-sessions", headers=client.admin).json()
    assert res["deleted"] == 1
    res = client.delete("/api/v1/admin/chat/expired-sessions", params={"older_than_days": 0}, headers=client.admin).json()
    assert res["deleted"] == 1
    with session_factory() as s:
        assert len(s.scalars(select(ChatSession)).all()) == 1
        assert len(s.scalars(select(ChatMessage)).all()) == 2      # messages went with their sessions
