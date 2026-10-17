"""Phase 7 tests: indexing rules, ranking, intent weighting, placeholders, thresholds, live updates."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database.database import Base, get_db
from app.main import app
from app.models import (FAQ, Document, Employee, Facility, HandbookSection, KnowledgeChunk, LibraryBook, Office,
                        Position, Room, SchoolHistory)
from app.services import retrieval as rv
from app.services.retrieval import clean_value, retrieve, split_passages

PH = "[ADMIN: ADD VERIFIED PGPC INFORMATION]"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    rv.clear_index_cache()
    with Session_() as s:
        reg = Office(name="Registrar Office", building="Main Building", floor="1", room_number="102",
                     contact_number="043-111-2222")
        cash = Office(name="Cashier", description=PH)
        reg_pos = Position(name="College Registrar", description="Keeps student records.")
        lab = Facility(name="Computer Laboratory", building="Annex", operating_hours="8am-5pm",
                       available_equipment="40 desktop computers")
        s.add_all([reg, cash, reg_pos, lab])
        s.flush()
        s.add_all([
            Employee(first_name="Maria", last_name="Santos", position_id=reg_pos.id, office_id=reg.id, status="active"),
            Employee(first_name="Joy Hinanay", last_name="Abu", description=f"Listed. {PH}", status="roster-2026"),
            Room(room_number="201", building="Annex", floor="2", room_type="Lecture room"),
            Room(room_number="101", building="Main Building", floor="1", facility_id=lab.id),
            HandbookSection(title="Section H - Absences and Tardiness", category="Chapter III", source_page="10",
                            source_document="PGPC Student Handbook",
                            content="A student who is absent for more than twenty percent of class meetings "
                                    "shall be dropped from the subject. Excused absences need valid proof."),
            HandbookSection(title="Section A - Scholarships", category="Chapter VII", source_page="21",
                            content="Scholarships are offered to qualified students who keep a high general average."),
            SchoolHistory(title="Founding of PGPC", year="2019", content="PGPC was established by the municipality."),
            FAQ(question="How do I request a transcript?", answer="Go to the registrar.", is_active=True),
            FAQ(question="How many students are enrolled per program?", answer="Secret numbers.", is_active=False),
            LibraryBook(title="Introduction to Algorithms", author="Cormen", availability="available"),
        ])
        doc_a = Document(title="Active Memo", file_name="a.txt", file_type="txt", status="active")
        doc_b = Document(title="Old Memo", file_name="b.txt", file_type="txt", status="archived")
        s.add_all([doc_a, doc_b])
        s.flush()
        s.add_all([KnowledgeChunk(document_id=doc_a.id, title="Parking", content="Parking is allowed behind the gym."),
                   KnowledgeChunk(document_id=doc_b.id, title="Helipad", content="The helipad is on the roof.")])
        s.commit()
        yield s
    rv.clear_index_cache()


def top(db, q, intent=None):
    return retrieve(db, q, intent)


# ------------------------------------------------------------------ helpers
def test_clean_value_strips_placeholder():
    text, had = clean_value(f"Room 5. Details: {PH}")
    assert had and "ADMIN" not in text
    assert clean_value(None) == ("", False)


def test_split_passages_keeps_everything_and_limits_size():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(12))
    parts = split_passages(text)
    assert len(parts) > 1 and all(len(p) <= rv.PASSAGE_MAX + 50 for p in parts)
    assert "Paragraph 11." in parts[-1]
    assert split_passages("short") == ["short"] and split_passages("  ") == []


# ------------------------------------------------------------------ ranking
def test_office_question_finds_office(db):
    r = top(db, "Where is the registrar office?", "office_location")
    assert r.found and r.best.source_type == "office" and r.best.title == "Registrar Office"
    assert r.best.fields["room_number"] == "102"
    assert "Main Building" in r.best.content


def test_employee_name_search(db):
    r = top(db, "who is maria santos", "employee_info")
    assert r.best.source_type == "employee" and r.best.title == "Maria Santos"
    assert r.best.fields["position"] == "College Registrar" and r.confidence == "high"


def test_room_number_search(db):
    r = top(db, "where is room 201", "room_location")
    assert r.best.source_type == "room" and r.best.fields["room_number"] == "201"
    assert top(db, "where is room 101", "room_location").best.fields["building"] == "Main Building"


def test_handbook_synonym_attendance_finds_absences(db):
    r = top(db, "what is the policy on attendance", "handbook_policy")
    assert r.best.source_type == "handbook" and "Absences" in r.best.title
    assert r.best.source == "PGPC Student Handbook, page 10"


def test_faq_and_library_and_history_and_facility(db):
    assert top(db, "how do i request a transcript", "faq_general").best.source_type == "faq"
    assert top(db, "is there a book about algorithms", "library_info").best.source_type == "library"
    assert top(db, "when was pgpc established", "school_history").best.source_type == "history"
    r = top(db, "what time does the computer laboratory open", "facility_info")
    assert r.best.source_type == "facility" and r.best.fields["operating_hours"] == "8am-5pm"


def test_typo_is_corrected_with_knowledge_base_words(db):
    r = top(db, "wher is the registrer ofice", "office_location")
    assert r.best.title == "Registrar Office"


def test_intent_prefers_matching_source(db):
    # "registrar" appears in an office, an employee position and an FAQ; the intent decides which comes first.
    assert top(db, "registrar", "office_location").best.source_type == "office"
    assert top(db, "registrar", "employee_info").best.source_type in {"employee", "position"}


# ------------------------------------------------------------------ honesty rules
def test_unknown_topic_is_not_found(db):
    r = top(db, "what is the price of a swimming pool membership", "facility_info")
    assert not r.found and r.confidence == "none"


def test_gibberish_and_empty_are_not_found(db):
    for q in ["zxqv wlpk", "", "???", "the a an"]:
        r = top(db, q)
        assert not r.found and r.hits == []


def test_small_talk_and_out_of_scope_never_search(db):
    for intent in ("greeting", "thanks", "goodbye", "bot_info", "out_of_scope"):
        r = top(db, "registrar office", intent)
        assert r.hits == [] and not r.found


def test_inactive_faq_is_never_returned(db):
    r = top(db, "how many students are enrolled per program", "enrollment_info")
    assert all(h.source_type != "faq" or h.title != "How many students are enrolled per program?" for h in r.hits)
    assert not any("Secret" in h.content for h in r.hits)


def test_archived_document_chunks_are_not_searched(db):
    assert top(db, "where is the helipad").hits == [] or not top(db, "where is the helipad").found
    assert top(db, "where is the parking", None).best.source_type == "document"


def test_placeholders_never_reach_the_content(db):
    r = top(db, "who is joy abu", "employee_info")
    assert r.best.title == "Joy Hinanay Abu" and r.best.incomplete
    assert "ADMIN" not in r.best.content and "Listed" not in r.best.content
    cashier = top(db, "where is the cashier", "office_location").best
    assert cashier.title == "Cashier" and cashier.incomplete and "ADMIN" not in cashier.content


def test_complete_records_are_not_flagged_incomplete(db):
    assert not top(db, "where is the registrar office", "office_location").best.incomplete


def test_seeded_roster_group_headings_are_not_searchable(db):
    db.add(Position(name="Faculty", description=f"Group heading. Specific job titles: {PH}"))
    db.commit()
    assert not any(h.source_type == "position" and h.title == "Faculty" for h in top(db, "faculty").hits)


# ------------------------------------------------------------------ scoring & cache
def test_scores_are_sorted_and_bounded(db):
    r = top(db, "scholarship", "handbook_policy")
    scores = [h.score for h in r.hits]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)


def test_confidence_levels(db):
    assert rv.confidence_level(0.9) == "high"
    assert rv.confidence_level(0.65) == "medium"
    assert rv.confidence_level(0.4) == "low"
    assert rv.confidence_level(0.1) == "none"


def test_total_matches_counts_records_above_threshold(db):
    for i in range(3):
        db.add(Employee(first_name=f"Ana{i}", last_name="Reyes", status="active"))
    db.commit()
    assert top(db, "reyes", "employee_info").total_matches == 3


def test_index_rebuilds_when_admin_adds_data_and_when_faq_is_deactivated(db):
    assert not top(db, "where is the guidance office", "office_location").found
    db.add(Office(name="Guidance Office", building="Main Building", floor="2"))
    db.commit()
    assert top(db, "where is the guidance office", "office_location").best.title == "Guidance Office"
    faq = db.query(FAQ).filter(FAQ.is_active.is_(True)).first()
    faq.is_active = False
    db.commit()
    assert not any(h.source_type == "faq" for h in top(db, "how do i request a transcript", "faq_general").hits)
    db.delete(db.query(Office).filter_by(name="Guidance Office").one())
    db.commit()
    assert not top(db, "where is the guidance office", "office_location").found


def test_empty_database_does_not_crash():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    rv.clear_index_cache()
    with sessionmaker(bind=engine)() as s:
        r = retrieve(s, "where is the registrar office", "office_location")
        assert not r.found and r.hits == []
    rv.clear_index_cache()


# ------------------------------------------------------------------ endpoint
def test_search_endpoint(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        body = c.get("/api/v1/search", params={"q": "Hi, where can I find the registrar office in PGPC?"}).json()
        assert body["intent"]["name"] == "office_location" and body["found"]
        assert body["results"][0]["title"] == "Registrar Office"
        assert "content" not in body["results"][0] and "snippet" in body["results"][0]
        joke = c.get("/api/v1/search", params={"q": "tell me a joke"}).json()
        assert joke["found"] is False and joke["results"] == []
        assert c.get("/api/v1/search", params={"q": ""}).status_code == 422
        assert c.get("/api/v1/search", params={"q": "x" * 3000}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_location_question_is_not_answered_by_a_handbook_paragraph(db):
    """No Guidance Office exists; a handbook passage that merely mentions "office" must not answer it."""
    db.add(HandbookSection(title="Section C - Change of Matriculation", source_page="12",
                           content="Students who wish to change course must see the registrar office and fill in a form "
                                   "approved by the dean before the end of the enrollment period."))
    db.commit()
    r = top(db, "where is the registrar office located", "office_location")
    assert r.best.source_type == "office"                      # the real office still wins
    r = top(db, "where is the library office", "office_location")
    assert not r.found


def test_facility_hours_are_searchable(db):
    """A question about "hours" or "what time ... open" must reach a facility that stores operating_hours."""
    for q in ("computer laboratory hours", "what time does the computer laboratory open"):
        r = top(db, q)
        assert r.best.source_type == "facility" and r.best.fields["operating_hours"] == "8am-5pm", q
