"""Tests for the official enrollment link ("how do I enroll?" -> https://pgpclaunch.padregarcia.gov.ph/)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import quick_links as ql
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer

URL = "https://pgpclaunch.padregarcia.gov.ph/"


def test_the_default_link_is_the_pgpc_enrollment_page():
    assert get_settings().enrollment_url == URL


def test_how_questions_get_the_link():
    for q in ("how do i enroll", "how to enroll", "how can i enroll online", "where can i enroll", "enrollment",
              "enroll", "i want to enroll", "can i enroll", "online enrollment", "enrollment procedure",
              "steps in enrollment", "how to enrol", "pre enrollment"):
        assert ql.enrollment_mode(q) == "how", q


def test_requirement_questions_keep_the_handbook_answer_and_add_the_link():
    for q in ("what are the requirements for enrollment", "what documents do i need to enroll",
              "enrollment requirements"):
        assert ql.enrollment_mode(q) == "requirements", q


def test_other_enrollment_topics_are_left_alone():
    for q in ("how much is the enrollment fee", "what is the late enrollment policy", "when is the enrollment",
              "who is the dean", "how many students enrolled", "tuition fees", "what is the refund policy"):
        assert ql.enrollment_mode(q) is None, q


def test_link_is_added_before_the_source_line():
    text = ql.add_link_to_answer("Some answer.\n\nSource: PGPC Student Handbook, page 6", URL)
    assert text.index(URL) < text.index("Source: PGPC Student Handbook")
    assert text.endswith("Source: PGPC Student Handbook, page 6")
    assert ql.add_link_to_answer("No source line", URL).endswith(URL)


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        text = seed.HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace")
        for r in seed.parse_handbook(text):
            s.add(HandbookSection(source_document=seed.HANDBOOK_SOURCE, **r))
        seed.seed_employees(s)
        seed.seed_offices(s)
        s.commit()
        rv.clear_index_cache()
        yield s
    rv.clear_index_cache()


def test_pipeline_gives_the_link_for_many_wordings(db):
    for q in ("how do i enroll", "How to enroll?", "paano mag enroll", "how to enrol", "wer can i enroll",
              "pls tell me how to enrol online", "enrollment", "i want to enroll"):
        a = generate_answer(db, q)
        assert a.found and a.kind == "answer" and URL in a.text, q
        assert a.sources and a.sources[0]["type"] == "link"
        assert a.text.rstrip().endswith(("Source: PGPC online enrollment", "Pinagmulan: PGPC online enrollment"))
        assert a.suggestions, q                                      # follow-up buttons still appear


def test_requirements_show_the_real_handbook_section_and_the_link(db):
    a = generate_answer(db, "what are the requirements for enrollment")
    assert "PRE-ENROLLMENT REQUIREMENTS AND PROCEDURE" in a.text and "medical clearance" in a.text
    assert "NSTP" not in a.text and "WITHDRAWAL" not in a.text.upper().split("PRE-ENROLLMENT")[0]
    assert URL in a.text and a.text.index(URL) < a.text.index("Source: PGPC Student Handbook")


def test_fees_and_policy_questions_do_not_get_the_link(db):
    for q in ("how much is the enrollment fee", "what is the late enrollment policy"):
        assert URL not in generate_answer(db, q).text, q


def test_two_questions_in_one_message_both_answered(db):
    a = generate_answer(db, "how do i enroll and who is the president of pgpc")
    assert URL in a.text and "Nino J. Vinas" in a.text


def test_the_link_can_be_switched_off_in_settings(db, monkeypatch):
    import app.services.answer_generator as ag
    off = get_settings().model_copy(update={"enrollment_url": ""})
    monkeypatch.setattr(ag, "get_settings", lambda: off)
    assert URL not in generate_answer(db, "how do i enroll").text


def test_the_link_can_be_changed_in_settings(db, monkeypatch):
    import app.services.answer_generator as ag
    other = get_settings().model_copy(update={"enrollment_url": "https://example.edu/enroll"})
    monkeypatch.setattr(ag, "get_settings", lambda: other)
    a = generate_answer(db, "how do i enroll")
    assert "https://example.edu/enroll" in a.text and URL not in a.text
