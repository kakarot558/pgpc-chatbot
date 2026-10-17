"""Tests for: admin quick links, 👍/👎 feedback, grouped unanswered report, Filipino replies, safe DB update."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import hash_password
from app.database import seed
from app.database.database import Base, get_db
from app.database.ensure_schema import ensure_schema
from app.main import app
from app.models import ChatMessage, HandbookSection, QuickLink, User
from app.services import filipino_reply as fr
from app.services import quick_links as ql
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer


# ------------------------------------------------------------------ pure pieces
def test_keywords_and_matching():
    from types import SimpleNamespace as N
    links = [N(title="Scholarship", keywords="scholarship application, apply scholarship", url="https://x.edu/s", message=None, is_active=True),
             N(title="Portal", keywords="student portal", url="https://x.edu/p", message="Open it:", is_active=True),
             N(title="Hidden", keywords="clearance", url="https://x.edu/c", message=None, is_active=False)]
    assert ql.match_link("how do i apply for a scholarship", links).title == "Scholarship"
    assert ql.match_link("where is the student portal", links).title == "Portal"
    assert ql.match_link("how to get clearance", links) is None          # inactive
    assert ql.match_link("what is the dress code", links) is None
    assert ql.valid_url("https://a.b/c") and not ql.valid_url("javascript:alert(1)") and not ql.valid_url("https://a b")


def test_filipino_translates_only_the_chatbot_sentences():
    out = fr.localize('Here is what the PGPC Student Handbook says about "haircut":\n- No. 3: Long hair for boys\nSource: PGPC Student Handbook')
    lines = out.split("\n")
    assert lines[0].startswith("Narito ang nakasaad") and lines[1] == "- No. 3: Long hair for boys"
    assert lines[2] == "Pinagmulan: PGPC Student Handbook"
    assert fr.localize("Dr. Ana Cruz is the College President of PGPC.") == "Si Dr. Ana Cruz ang College President ng PGPC."
    assert fr.localize("Some handbook rule text.") == "Some handbook rule text."


# ------------------------------------------------------------------ API
@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(User(username="boss", email="b@x.com", password_hash=hash_password("AdminPass1"), role="admin"))
        text_ = seed.HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace")
        for r in seed.parse_handbook(text_):
            s.add(HandbookSection(source_document=seed.HANDBOOK_SOURCE, **r))
        s.commit()
    rv.clear_index_cache()

    def override():
        with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login", data={"username": "boss", "password": "AdminPass1"}).json()["access_token"]
    yield c, {"Authorization": "Bearer " + tok}, Session
    app.dependency_overrides.clear()
    rv.clear_index_cache()


def test_admin_quick_link_is_given_to_students(env):
    c, admin, _ = env
    r = c.post("/api/v1/admin/quick-links", headers=admin, json={
        "title": "Scholarship application", "keywords": "scholarship application, apply scholarship",
        "url": "https://example.edu/scholarship", "message": "Apply for a scholarship here:"})
    assert r.status_code in (200, 201), r.text
    rv.clear_index_cache()
    a = c.post("/api/v1/chat", json={"message": "how do i apply for a scholarship"}).json()
    assert "https://example.edu/scholarship" in a["answer"] and a["answer"].startswith("Apply for a scholarship here:")
    assert a["found"] and a["message_id"]


def test_quick_link_rejects_a_bad_url_and_empty_keywords(env):
    c, admin, _ = env
    bad = {"title": "X", "keywords": "x thing", "url": "javascript:alert(1)"}
    assert c.post("/api/v1/admin/quick-links", headers=admin, json=bad).status_code == 422
    assert c.post("/api/v1/admin/quick-links", headers=admin,
                  json={"title": "Y", "keywords": ",,", "url": "https://a.b"}).status_code == 422


def test_feedback_roundtrip_and_admin_views(env):
    c, admin, Session = env
    first = c.post("/api/v1/chat", json={"message": "what is the haircut policy"}).json()
    token = first["session_token"]
    h = {"X-Session-Token": token}
    assert c.post("/api/v1/chat/feedback", headers=h, json={"message_id": first["message_id"], "value": "up"}).status_code == 200
    second = c.post("/api/v1/chat", json={"message": "what is the policy on fighting", "session_token": token}).json()
    r = c.post("/api/v1/chat/feedback", headers=h, json={"message_id": second["message_id"], "value": "down", "comment": "not there"})
    assert r.json()["feedback"] == "down"
    fb = c.get("/api/v1/admin/chat/feedback?value=down", headers=admin).json()
    assert fb["total"] == 1 and fb["items"][0]["comment"] == "not there" and "fighting" in fb["items"][0]["question"]
    s = c.get("/api/v1/admin/chat/summary", headers=admin).json()
    assert s["helpful"] == 1 and s["not_helpful"] == 1
    assert c.post("/api/v1/chat/feedback", headers=h, json={"message_id": second["message_id"], "value": "clear"}).json()["feedback"] is None


def test_feedback_cannot_rate_someone_elses_answer_or_without_a_session(env):
    c, _, _ = env
    mine = c.post("/api/v1/chat", json={"message": "what is the haircut policy"}).json()
    other = c.post("/api/v1/chat", json={"message": "what is the dress code"}).json()
    assert c.post("/api/v1/chat/feedback", headers={"X-Session-Token": other["session_token"]},
                  json={"message_id": mine["message_id"], "value": "up"}).status_code == 404
    assert c.post("/api/v1/chat/feedback", json={"message_id": mine["message_id"], "value": "up"}).status_code == 404
    assert c.post("/api/v1/chat/feedback", headers={"X-Session-Token": other["session_token"]},
                  json={"message_id": 1, "value": "bad"}).status_code == 422


def test_unanswered_questions_are_grouped_with_a_count(env):
    c, admin, _ = env
    for q in ("what is the policy on fighting", "What is the policy on fighting?", "what is the policy on parking"):
        c.post("/api/v1/chat", json={"message": q})
    items = c.get("/api/v1/admin/chat/unanswered", headers=admin).json()["items"]
    assert items[0]["count"] == 2 and "fighting" in items[0]["question"].lower()
    assert any("parking" in i["question"].lower() for i in items)
    assert c.get("/api/v1/admin/chat/unanswered").status_code in (401, 403)


def test_filipino_question_gets_filipino_framing_through_the_api(env):
    c, _, _ = env
    a = c.post("/api/v1/chat", json={"message": "bawal ba ang tattoo"}).json()
    assert a["answer"].startswith("Maikling sagot: hindi.")
    assert "Pinagmulan:" in a["answer"] and "Source:" not in a["answer"]
    en = c.post("/api/v1/chat", json={"message": "can i wear sandals"}).json()["answer"]
    assert en.startswith("Short answer: no.")


# ------------------------------------------------------------------ old databases are updated safely
def test_old_database_is_updated_without_losing_data():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE quick_links"))
        conn.execute(text("ALTER TABLE chat_messages DROP COLUMN feedback"))
        conn.execute(text("ALTER TABLE chat_messages DROP COLUMN feedback_comment"))
    changed = ensure_schema(engine)
    assert "created table quick_links" in changed and "added column chat_messages.feedback" in changed
    cols = {c["name"] for c in inspect(engine).get_columns("chat_messages")}
    assert {"feedback", "feedback_comment"} <= cols
    assert ensure_schema(engine) == []                      # running again changes nothing
