"""Tests for multi-turn conversations about handbook topics, contact questions, 'head of the library',
student wording -> handbook wording, and garbled handbook headings."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import followup as fu
from app.services import input_reader as ir
from app.services import policy_detail as pd
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer
from app.services.chat_service import _topic_of, answer_message


# ------------------------------------------------------------------ pure pieces
def test_new_subject_is_found_after_what_about():
    assert fu.new_subject("what about the dress code") == "the dress code"
    assert fu.new_subject("how about tattoo?") == "tattoo"
    assert fu.new_subject("and slippers") == "slippers"
    for q in ("what about its hours", "and the penalty?", "what about the sanctions", "what about his email"):
        assert fu.new_subject(q) is None, q


def test_policy_detail_words_are_a_follow_up_only_for_handbook_topics():
    assert fu.detect_cue("what are the sanctions", "handbook") == "weak"
    assert fu.detect_cue("what are the sanctions", "office") == "none"
    assert fu.detect_cue("and the penalty?", "handbook") == "weak"


def test_follow_up_is_rewritten_with_the_policy_topic():
    topic = fu.Topic("handbook", None, "haircut")
    assert fu.rewrite("what are the sanctions", topic, "weak") == "sanctions for haircut"
    assert fu.rewrite("and the penalties", topic, "weak") == "penalties for haircut"


def test_student_wording_becomes_handbook_wording():
    assert ir.apply_domain_phrases("how do i get an excuse letter") == ("how do i get an excuse slip", True)
    text, loud = ir.apply_domain_phrases("can i use my cell phone")
    assert text == "can i use my cellphone" and loud is False          # a spelling variant is not announced
    assert ir.apply_domain_phrases("how do i change my course")[0] == "how do i shifting course"


def test_garbled_handbook_headings_are_repaired():
    assert pd.fix_ocr_heading("WEETLON A-LIBRARY SERVICES") == "SECTION A - LIBRARY SERVICES"
    assert pd.fix_ocr_heading("Weetlon A-Library Services") == "Section A - Library Services"
    assert pd.fix_ocr_heading("Section H - Absences and Tardiness") == "Section H - Absences and Tardiness"
    assert pd.fix_ocr_heading("Chapter X - Library Rules") == "Chapter X - Library Rules"
    assert pd.fix_ocr_heading("Dress Code Policy") == "Dress Code Policy"


def test_topic_label_drops_request_words():
    assert pd._label_topic(["scholarship"], "how do i apply for a scholarship".split()) == "scholarship"
    assert pd._label_topic(["transfer"], "can i transfer from another school".split()) == "transfer"


# ------------------------------------------------------------------ with the real handbook
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


def chat(db, questions):
    """Runs a conversation the way the chat does: the topic of each answer is passed to the next question."""
    topic, out = None, []
    for q in questions:
        ans, interpreted = answer_message(db, q, topic)
        new = _topic_of(ans)
        topic = new or topic
        out.append((ans, interpreted))
    return out


def test_what_about_another_policy_answers_that_policy(db):
    turns = chat(db, ["what is the haircut policy", "what about the dress code", "how about tattoo"])
    assert "DRESS CODE POLICY" in turns[1][0].text.upper() and turns[1][1] == "the dress code"
    assert "tattoo" in turns[2][0].text.lower() and "hair" not in turns[2][0].text.lower().split("tattoo")[0][-40:]


def test_sanctions_follow_up_stays_on_the_topic(db):
    turns = chat(db, ["what is the haircut policy", "what are the sanctions"])
    a, interpreted = turns[1]
    assert interpreted == "sanctions for haircut"
    assert "Not in proper hair cut" in a.text and "1 month suspension" in a.text


def test_follow_up_after_a_yes_no_answer(db):
    turns = chat(db, ["can i wear sandals", "and the penalty?"])
    assert turns[1][1] == "penalty for sandals" and "1 month suspension" in turns[1][0].text


def test_a_bare_topic_word_is_answered_even_when_search_is_unsure(db):
    a = generate_answer(db, "slippers")
    assert a.found and "sandals and slippers" in a.text.lower()


def test_email_of_the_president_follow_up_uses_the_roster(db):
    turns = chat(db, ["who is the president of pgpc", "what is his email"])
    a = turns[1][0]
    assert "email" in a.text.lower() and "Vi\u00f1as" in a.text and "don't have" in a.text.lower()


def test_contact_of_an_official_without_a_follow_up(db):
    a = generate_answer(db, "what is the email of the president")
    assert not a.found and "Nino J. Vinas" in a.text and "don't have an email" in a.text
    assert "Joy H. Abu" in generate_answer(db, "what is the contact number of the dean").text


def test_office_contact_questions_are_not_taken_by_the_people_module(db):
    a = generate_answer(db, "what is the contact number of the registrar office")
    assert "who the registrar" not in a.text


def test_head_of_a_place_says_it_is_not_on_file(db):
    for q in ("who is the head of the library", "who is the head of the registrar office"):
        a = generate_answer(db, q)
        assert not a.found and "don't have a record of who heads" in a.text, q
    assert "Nino J. Vinas" in generate_answer(db, "who is the head of pgpc").text


def test_excuse_letter_finds_the_excuse_slip_rules(db):
    a = generate_answer(db, "how do i get an excuse letter")
    assert a.found and "EXCUSE SLIP" in a.text.upper() and a.understood_as == "how do i get an excuse slip"


def test_a_missing_topic_is_named_in_the_reply(db):
    a = generate_answer(db, "what is the policy on fighting")
    assert not a.found and 'anything about "fighting"' in a.text


def test_library_headings_are_readable(db):
    text = generate_answer(db, "what are the library rules").text
    assert "WEETLON" not in text.upper() and "LIBRARY RULES AND REGULATIONS" in text.upper()


def test_answers_say_what_not_everything(db):
    text = generate_answer(db, "what is the haircut policy").text
    assert text.splitlines()[0].startswith('Here is what the PGPC Student Handbook says about "haircut"')
    assert "Here is everything" not in text


def test_the_old_follow_ups_for_offices_still_work(db):
    turns = chat(db, ["where is the registrar office", "what are its hours"])
    assert turns[1][1] == "what are the hours of Office of the Registrar"
