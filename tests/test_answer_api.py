"""Phase 8 tests: /api/v1/answer end to end on an in-memory SQLite database, plus the offices/facilities seed."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base, get_db
from app.main import app
from app.models import FAQ, Facility, Office
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def ask(client, q):
    res = client.get("/api/v1/answer", params={"q": q})
    assert res.status_code == 200
    return res.json()


# ------------------------------------------------------------------ the endpoint
def test_greeting_and_blank_and_validation(client):
    assert ask(client, "hello")["kind"] == "small_talk"
    assert ask(client, "     ")["kind"] == "empty"
    assert client.get("/api/v1/answer", params={"q": ""}).status_code == 422
    assert client.get("/api/v1/answer").status_code == 422


def test_empty_database_never_guesses(client):
    body = ask(client, "where is the registrar office")
    assert body["success"] and not body["found"] and body["kind"] == "not_found"
    assert body["sources"] == []


def test_office_answer_uses_the_stored_record(client, session_factory):
    with session_factory() as s:
        s.add(Office(name="Registrar Office", building="Main Building", floor="1", room_number="102"))
        s.commit()
    body = ask(client, "Where is the registrar office?")
    assert body["found"] and "Room 102" in body["answer"] and body["sources"][0]["type"] == "office"


def test_inactive_faq_is_never_used(client, session_factory):
    with session_factory() as s:
        s.add(FAQ(question="How many students are enrolled per program?", answer="Secret numbers 999.",
                  is_active=False))
        s.commit()
    body = ask(client, "how many students are enrolled per program")
    assert "999" not in body["answer"]


def test_out_of_scope_is_declined(client):
    body = ask(client, "what is the capital of France")
    assert not body["found"] and "Paris" not in body["answer"]


# ------------------------------------------------------------------ offices and facilities seed
def test_seed_adds_offices_and_facilities_once(session_factory):
    with session_factory() as s:
        assert seed.seed_offices(s) == (len(seed.OFFICES), 0)
        assert seed.seed_facilities(s) == (len(seed.FACILITIES), 0)
        s.commit()
    with session_factory() as s:      # second run changes nothing
        assert seed.seed_offices(s) == (0, len(seed.OFFICES))
        assert seed.seed_facilities(s) == (0, len(seed.FACILITIES))
        assert len(s.scalars(select(Office)).all()) == len(seed.OFFICES)


def test_seeded_records_do_not_invent_locations(session_factory):
    with session_factory() as s:
        seed.seed_offices(s)
        seed.seed_facilities(s)
        s.commit()
        for o in s.scalars(select(Office)):
            assert not (o.building or o.floor or o.room_number or o.contact_number or o.email)
        for f in s.scalars(select(Facility)):
            assert not (f.building or f.location)


def test_chatbot_answers_seeded_clinic_hours_and_admits_missing_location(client, session_factory):
    with session_factory() as s:
        seed.seed_facilities(s)
        s.commit()
    hours = ask(client, "what are the clinic hours")
    assert hours["found"] and "Monday-Friday, 8 AM-5 PM" in hours["answer"] and "[ADMIN" not in hours["answer"]
    where = ask(client, "where is the college clinic")
    assert where["found"] and "I don't have the exact location" in where["answer"]


def test_chatbot_answers_seeded_office_but_admits_missing_location(client, session_factory):
    with session_factory() as s:
        seed.seed_offices(s)
        s.commit()
    body = ask(client, "where is the registrar office")
    assert body["found"] and "Office of the Registrar" in body["answer"]
    assert "I don't have the exact location" in body["answer"] and "[ADMIN" not in body["answer"]
