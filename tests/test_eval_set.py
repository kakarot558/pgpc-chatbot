"""The fixed question set must keep passing: it catches regressions after any change."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer
import csv
from ml.evaluation.run_answer_eval import FILE


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        for r in seed.parse_handbook(seed.HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace")):
            s.add(HandbookSection(source_document=seed.HANDBOOK_SOURCE, **r))
        seed.seed_employees(s)
        seed.seed_offices(s)
        from app.database.campus_data import apply as apply_campus
        apply_campus(s)
        s.commit()
        rv.clear_index_cache()
        yield s
    rv.clear_index_cache()


def test_every_question_in_the_fixed_set_still_gets_its_expected_answer(db):
    rows = list(csv.DictReader(FILE.open(encoding="utf-8")))
    assert len(rows) >= 30
    wrong = [r["question"] for r in rows if r["expected"].lower() not in generate_answer(db, r["question"]).text.lower()]
    assert wrong == [], f"regressions: {wrong}"


def test_room_questions_use_the_floor_plan(db):
    t = lambda q: generate_answer(db, q).text
    assert "Yellow Building" in t("where is com lab 2") and "Computer Laboratory 2" in t("where is com lab 2")
    assert "in the Yellow Building" not in t("where is the moot court")
    assert "Lecture Room 1" in t("where is room 1") and "2nd floor" in t("where is lr 3")
    listing = t("what rooms are in building 2")
    assert "Moot Court" in listing and "Guidance Office" in listing


def test_office_location_mentions_shared_room_and_no_missing_note(db):
    t = lambda q: generate_answer(db, q).text
    reg = t("where is the registrar office")
    assert "1st floor" in reg and "shares a room with the Admission Office" in reg and "Note:" not in reg
    cash = t("where is the cashier")
    assert "Accounting Office" in cash and "Human Resources" in cash and "Note:" not in cash


def test_new_or_current_president_means_the_president(db):
    for q in ("new president", "who is the current president", "who is the new college president"):
        t = generate_answer(db, q).text
        assert "Manalo" in t and "Vinas" not in t


def test_directory_positions_for_every_title(db):
    t = lambda q: generate_answer(db, q).text
    for q, who in [("who is the director of research and extension", "Viñas"), ("who heads research and extension", "Viñas"),
                   ("head of the registrar office", "Solis"), ("who is the head of the library", "Contreras"),
                   ("who is the program chair of bscs", "Sebuc"), ("who is the vpaf", "Diaz"),
                   ("who is the dean of ccba", "Aliwalas"), ("who is the school nurse", "Padua")]:
        assert who.lower() in t(q).lower().replace("ñ", "n") or who in t(q), q


def test_floors_from_the_white_building_sheet(db):
    t = lambda q: generate_answer(db, q).text
    assert "2nd floor" in t("where is lr 4") and "1st floor" in t("where is lecture room 1")
    crs = t("where is the comfort room")
    assert "male" in crs and "2nd floor" in crs and "PWD" in crs
    assert "BSCS" in t("who is the program chair of bscs")


def test_where_is_a_person_and_who_works_where(db):
    t = lambda q: generate_answer(db, q).text
    assert "located at: 1st floor, White Building, Registrar Office & Admission Office" in t("where is nicky solis")
    assert "2nd floor" in t("where is the dean of ccba") and "2nd floor" in t("what floor is the president")
    assert "Solis" in t("who works in the registrar office") and "Mangurali" in t("who is in the accounting office")
    ground, second = t("what is on the ground floor"), t("what is on the 2nd floor")
    assert "Office of the Registrar" in ground and "Lecture Room 4" in second and "Registrar" not in second
    assert "Buya" in t("where is the guidance counselor")


def test_short_titles_are_not_spell_corrected(db):
    t = lambda q: generate_answer(db, q).text
    assert "Renan" in t("who is the program chair of crim")
    assert "Diaz" in t("who is the vice president for admin and finance") and "Manalo" in t("who is the oic president")


def test_bare_names_and_shared_surnames(db):
    t = lambda q: generate_answer(db, q).text
    assert "Registrar" in t("solis") and "Director of Research and Extension" in t("dr vinas")
    both = t("who is diaz")
    assert "more than one" in both and "Romy" in both and "Ohmie" in both
    assert "Hazel" in t("who is gonzales")


def test_a_repeated_question_is_answered_once(db):
    once = generate_answer(db, "who is the president?").text
    many = generate_answer(db, "who is the president? " * 6).text
    assert many == once and many.count("Manalo") == 1
    diff = generate_answer(db, "who is the president? where is lr 3?").text
    assert "You asked 2 questions" in diff


def test_location_answers_use_floor_building_room_order(db):
    t = lambda q: generate_answer(db, q).text
    assert "1st floor, White Building, Registrar Office & Admission Office" in t("where is registrar")
    assert "1st floor, White Building, Registrar Office & Admission Office" in t("where is the registrar office")
    assert "1st floor, Yellow Building" in t("where is crime lab 1") and "2nd floor, Yellow Building" in t("where is the moot court")
    assert "2nd floor, White Building" in t("where is lr 6")
    assert "Registrar" not in t("what is on the 2nd floor")
