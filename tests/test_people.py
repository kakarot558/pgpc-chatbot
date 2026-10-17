"""Tests for 'who is the <role>' answers: officials named in the handbook, roles in the employee records, groups."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import Employee, HandbookSection, Position
from app.services import people as pp
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer

PAGE = """
PGPC BOARD OF TRUSTEES

Hon. Celsa B. Rivera
Municipal Mayor/Chairperson,
Board of Trustees

Dr. Nino J. Vinas
College President,
Board of Trustees

Mr. Christopher B. Comea
Board of Trustees

Student Handbook
Committee

Dr. Nino J. Vi\u00f1as
College President

Romy C. Diaz, LPT
Vice President for Administration and Finance

Joy H. Abu
College Dean

D. Awards Committee
In time for the awards deliberation, the College President constitutes an awards committee.
"""
SENTENCE = ("Dr. Nino J. Vinas was the first designated College President/ Vice President for Academic Affairs\n"
            "since March 1, 2024, up to present.")


# ------------------------------------------------------------------ reading the question
def test_role_questions_in_many_wordings():
    for q in ("who is the president of pgpc", "pgpc president", "who is the college president", "who is president",
              "who's the president of the college", "name of the president of pgpc"):
        r = pp.parse_role_question(q)
        assert r and r.role == ["president"] and pp.is_pgpc_qualifier(r.qualifier), q
    r = pp.parse_role_question("who is utility staff")
    assert r.role == ["utility"] and r.text == "utility staff"
    assert pp.parse_role_question("who are the board of trustees").text == "Board of Trustees"
    assert pp.parse_role_question("who is the vice president for academic affairs").role == \
        ["vice", "president", "academic", "affairs"]


def test_someone_elses_country_is_not_a_pgpc_question():
    r = pp.parse_role_question("who is the president of the united states")
    assert r and not pp.is_pgpc_qualifier(r.qualifier)


def test_names_and_rule_questions_are_not_role_questions():
    assert not pp.looks_like_role(pp.parse_role_question("who is joy abu").role)
    assert pp.parse_role_question("who can borrow books") is None
    assert pp.parse_role_question("where is the registrar office") is None
    assert pp.parse_role_question("how do i enroll") is None


def test_who_leads_pgpc_means_the_president():
    assert pp.parse_role_question("who leads pgpc").role == ["president"]


# ------------------------------------------------------------------ officials in the handbook text
def test_officials_are_read_from_signature_blocks_and_lists():
    offs = {o.key: o for o in pp.parse_officials(PAGE)}
    assert any("Municipal Mayor" in r for r in offs[("celsa", "rivera")].roles)
    vinas = offs[("nino", "vinas")]
    assert "College President" in vinas.roles and "Board of Trustees" in vinas.roles
    assert any("Administration and Finance" in r for r in offs[("romy", "diaz")].roles)
    assert offs[("joy", "abu")].roles == ["College Dean"]


def test_a_sentence_that_only_mentions_the_president_is_not_a_person():
    names = [o.name for o in pp.parse_officials(PAGE)]
    assert not any("Awards" in n for n in names)


def test_sentence_names_the_president_with_a_date():
    off = pp.parse_officials(SENTENCE)[0]
    assert "College President" in off.roles and "Vice President for Academic Affairs" in off.roles
    assert off.notes == ["designated since March 1, 2024"]


def test_president_does_not_match_vice_president_and_vice_mayor_only_the_vice_mayor():
    assert pp.role_matches("College President", ["president"])
    assert not pp.role_matches("Vice President for Administration and Finance", ["president"])
    assert pp.role_matches("Municipal Vice Mayor", ["vice", "mayor"])
    assert not pp.role_matches("Municipal Mayor", ["vice", "mayor"])
    assert pp.role_matches("Board of Trustees", ["trustees"])


# ------------------------------------------------------------------ with a database
@pytest.fixture()
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


def ask(db, q):
    return generate_answer(db, q)


def test_president_of_pgpc_is_answered_from_the_handbook(db):
    for q in ("who is the president of pgpc", "pgpc president", "Who is the College President?",
              "sino ang presidente ng pgpc", "who leads pgpc"):
        a = ask(db, q)
        assert a.found and "Nino J. Vinas" in a.text and "College President" in a.text, q
        assert "March 1, 2024" in a.text
        assert ("Employee record" in a.text or "Talaan ng empleyado" in a.text)            # linked to the roster entry Vi\u00f1as, Ni\u00f1o
        types = [x["type"] for x in a.sources]
        assert types[0] == "employee" and "handbook" in types       # the roster record comes first: "what is his email"


def test_other_officials(db):
    assert "Celsa" in ask(db, "who is the mayor").text
    assert "Micko" in ask(db, "who is the vice mayor").text
    assert "Joy H. Abu" in ask(db, "who is the dean").text
    assert "Romy C. Diaz" in ask(db, "who is the vice president for administration and finance").text
    trustees = ask(db, "who are the board of trustees").text
    for name in ("Celsa", "Micko", "Vinas", "Comea", "Manalo", "Calingasan", "Tapalla"):
        assert name in trustees, name


def test_security_guard_comes_from_the_roster_note(db):
    a = ask(db, "who is the security guard")
    assert a.found and "Luis Aragon" in a.text and "Kuya Guard" in a.text
    assert a.sources[0]["type"] == "employee"


def test_utility_staff_is_honest_when_no_titles_are_on_file(db):
    a = ask(db, "who is utility staff")
    assert not a.found and a.kind == "answer"
    assert "don't have a record" in a.text and "52" in a.text and "19" in a.text
    assert "Positions" in a.text                                  # tells the admin how to add it
    assert "couldn't find that person" not in a.text              # not the old dead-end message


def test_utility_staff_works_as_soon_as_the_admin_adds_the_position(db):
    pos = Position(name="Utility Staff", description="Maintenance and cleaning")
    db.add(pos)
    db.flush()
    for last in ("Padua", "Sulabo"):
        e = db.scalar(select(Employee).where(Employee.last_name == last))
        e.position_id = pos.id
    db.commit()
    rv.clear_index_cache()
    for q in ("who is utility staff", "who are the janitors", "who is the maintenance staff", "utility staff"):
        a = ask(db, q)
        assert a.found, q
        assert "Padua" in a.text and "Sulabo" in a.text, q
        assert "Aragon" not in a.text, q


def test_groups_are_listed_in_full_and_counted(db):
    faculty = ask(db, "who are the faculty").text
    assert "52 people" in faculty and "Joy Hinanay Abu" in faculty and "Cora" in faculty
    assert "19 people" in ask(db, "who are the administrative personnel").text
    assert "52" in ask(db, "how many faculty does pgpc have").text
    assert "19" in ask(db, "how many administrative personnel are there").text


def test_registrar_and_cashier_have_offices_but_no_person_yet(db):
    a = ask(db, "who is the registrar")
    assert "Office of the Registrar" in a.text and "has not been added yet" in a.text
    assert "Cashier" in ask(db, "who is the cashier").text


def test_the_old_paths_still_work(db):
    assert "Joy Hinanay Abu" in ask(db, "who is joy abu").text                    # a person's name
    assert ask(db, "who is the president of the united states").kind == "out_of_scope"
    assert ask(db, "hello").kind == "small_talk"
    assert "Not in proper hair cut" in ask(db, "what is the haircut policy").text   # earlier upgrade untouched
