"""Tests for the full-detail policy answers (haircut, dress code, cheating ...).

The first tests use a tiny made-up offense table; the later ones load the REAL handbook into an in-memory
database, because the whole point is that the flattened handbook text becomes one complete answer.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import policy_detail as pd
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer
from app.services.synonyms import SYNONYMS
from app.utils.text_cleaner import normalize_text

SAMPLE = """
Minor Offense
Nature of Offense
1. Eating inside the classroom
2. Blonde hair
3. Long hair for boys

Sanctions
Written/oral reprimand
Written/personal apologies

Formation sessions (counseling, moral
guidance, etc.) Up to 40 hours mandatory
work in the form of community service

The following are considered inimical to the dignity of the members of the community:

Major Offense
Offenses Against Order
1. Wearing sandals and slippers
2. Display of tattoo, blonde hair and
earing for boys
3. Not in proper hair cut as prescribed
by the college.

OFFENSE AGAINST ORDER
1. 1 month suspension
2. Dismissal (exclusion)/Expulsion

Offenses Against Property
1. Stealing

OFFENSE AGAINST PROPERTY
1. Dismissal (exclusion)/Expulsion
"""


def words(q):
    return normalize_text(q).split()


# ------------------------------------------------------------------ understanding the question
def test_topic_is_the_question_without_filler_and_detail_words():
    assert pd.topic_terms(words("what is the haircut policy")) == ["haircut"]
    assert pd.topic_terms(words("tell me the details about haircut violation")) == ["haircut"]
    assert pd.topic_terms(words("what is the dress code policy")) == ["dress"]
    assert pd.topic_terms(words("what are the rules about hair for boys")) == ["hair"]


def test_only_policy_or_detail_questions_get_the_full_answer():
    for q in ("what is the haircut policy", "tell me the details about haircut", "penalty for cheating",
              "explain the dress code"):
        assert pd.wants_full_detail(words(q)), q
    # narrow questions keep the short focused answer
    for q in ("how many absences are allowed", "where is the clinic", "when is enrollment", "who is the dean"):
        assert not pd.wants_full_detail(words(q)), q


def test_a_bare_topic_counts_but_a_narrow_question_does_not():
    assert pd.is_topic_only(words("haircut")) and pd.is_topic_only(words("dress code"))
    assert not pd.is_topic_only(words("how many books can i borrow"))


# ------------------------------------------------------------------ the offense table parser
def test_parser_knows_minor_from_major_and_the_category():
    idx = pd.parse_offenses(SAMPLE)
    by_text = {i.text: i for i in idx.items}
    assert by_text["Blonde hair"].table == "Minor" and by_text["Blonde hair"].number == "2"
    hair = by_text["Not in proper hair cut as prescribed by the college"]
    assert hair.table == "Major" and hair.category == "Offenses Against Order" and hair.number == "3"
    # a rule wrapped over two lines is one rule
    assert "Display of tattoo, blonde hair and earing for boys" in by_text


def test_parser_attaches_sanctions_to_the_right_group():
    idx = pd.parse_offenses(SAMPLE)
    assert idx.sanctions[("Minor", "general")][0] == "Written/oral reprimand"
    assert any(s.startswith("Formation sessions") and "community service" in s
               for s in idx.sanctions[("Minor", "general")])
    assert idx.sanctions[("Major", "order")] == ["1 month suspension", "Dismissal (exclusion)/Expulsion"]
    assert idx.sanctions[("Major", "property")] == ["Dismissal (exclusion)/Expulsion"]


def test_every_rule_about_the_topic_is_found_across_both_tables():
    idx = pd.parse_offenses(SAMPLE)
    found = pd.find_offense_items(idx, pd.term_groups(["haircut"], SYNONYMS))
    texts = {i.text for i in found}
    assert {"Blonde hair", "Long hair for boys", "Not in proper hair cut as prescribed by the college",
            "Display of tattoo, blonde hair and earing for boys"} <= texts
    assert "Stealing" not in texts and "Eating inside the classroom" not in texts


def test_compose_detail_has_class_sanctions_and_honest_notes():
    idx = pd.parse_offenses(SAMPLE)
    groups = pd.term_groups(["haircut"], SYNONYMS)
    items = pd.find_offense_items(idx, groups)
    out = pd.compose_detail(["haircut"], idx, items, [], [], groups, words("haircut policy"))
    text = out.text
    assert "MINOR OFFENSES" in text and "MAJOR OFFENSES" in text and "Offenses Against Order" in text
    assert "1 month suspension" in text and "Written/oral reprimand" in text
    assert "does not say which one applies" in text          # no invented rule-by-rule sanction mapping
    assert "confirmed with the Office of Student Affairs" in text      # blonde hair is both minor and major
    assert "Source: PGPC Student Handbook" in text


def test_nothing_found_means_no_detailed_answer():
    idx = pd.parse_offenses(SAMPLE)
    groups = pd.term_groups(["chess"], SYNONYMS)
    assert pd.compose_detail(["chess"], idx, pd.find_offense_items(idx, groups), [], [], groups) is None


def test_policy_block_needs_the_topic_word_not_just_a_synonym():
    blocks = ["Shall pay the ordered uniform, ID and medical fee.", "Dress Code Policy\nWear the uniform.\n1. Rule one\n2. Rule two"]
    groups = pd.term_groups(["dress"], SYNONYMS)
    got = pd.pick_policy_blocks(blocks, groups, {"dress"})
    assert got == [blocks[1]]                       # the unrelated withdrawal rule is left out
    assert pd.pick_policy_blocks(blocks[:1], groups, {"dress"}) == []


# ------------------------------------------------------------------ the real handbook
@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        text = seed.HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace")
        for r in seed.parse_handbook(text):
            s.add(HandbookSection(source_document=seed.HANDBOOK_SOURCE, **r))
        s.commit()
        rv.clear_index_cache()
        yield s
    rv.clear_index_cache()


def detail(db, q):
    return pd.build_detail_answer(db, words(q), SYNONYMS)


def test_real_handbook_haircut_answer_is_complete(db):
    text = detail(db, "what is the haircut policy").text
    for part in ("Blonde hair", "Long hair for boys", "Not in proper hair cut", "No. 30", "No. 10", "No. 11",
                 "Written/oral reprimand", "40 hours", "1 month suspension", "Dismissal (exclusion)/Expulsion",
                 "Offenses Against Order", "earrings for boys"):
        assert part in text, part
    assert "Stealing" not in text


def test_real_handbook_dress_code_shows_the_whole_policy_not_one_sentence(db):
    text = detail(db, "dress code policy").text
    text = text.replace("DRESS CODE POLICY ON WASHDAYS", "Dress Code Policy on Washdays")   # the heading is the label
    for part in ("Dress Code Policy on Washdays", "Prohibited Attire", "First Offense: Denied entry",
                 "Third Offense: Community service", "Schedule for Wearing School Uniforms"):
        assert part in text, part
    assert "CHANGE OF MATRICULATION" not in text.upper()          # a withdrawal rule that only says "uniform"


def test_real_handbook_cheating_finds_dishonesty_and_plagiarism_with_sanctions(db):
    text = detail(db, "what is the penalty for cheating").text
    assert "Offenses Involving Dishonesty" in text and "Plagiarism" in text
    assert "Dismissal (exclusion)/Expulsion" in text


def test_real_handbook_cellphone_rule_hidden_in_a_compound_rule_is_found(db):
    text = detail(db, "tell me the details about cellphone use").text
    assert "Using cell phone during classes" in text
    assert "Behavior considered unbecoming" in text


def test_real_handbook_topic_that_is_not_there_returns_none(db):
    assert detail(db, "what are the rules of chess") is None


# ------------------------------------------------------------------ through the whole pipeline
def test_pipeline_haircut_policy_returns_the_full_answer(db):
    for q in ("what is the haircut policy", "tell me the details about haircut", "haircut",
              "what are the rules about hair for boys"):
        a = generate_answer(db, q)
        assert a.found and a.kind == "answer", q
        assert "Not in proper hair cut" in a.text or "Long hair for boys" in a.text, q
        assert "1 month suspension" in a.text, q
        assert a.sources and a.sources[0]["type"] == "handbook"


def test_pipeline_narrow_questions_are_not_taken_over(db):
    a = generate_answer(db, "Where is the registrar office?")
    assert "Here is what the PGPC Student Handbook says" not in a.text
    assert generate_answer(db, "hello").kind == "small_talk"
    assert generate_answer(db, "tell me a joke").kind == "out_of_scope"


# ------------------------------------------------------------------ uniform / attire / schedule are one policy
def test_dress_question_detection():
    from app.services import policy_detail as p
    for q in ("uniform", "what is the attire", "what to wear", "what is the uniform schedule", "dress code",
              "what is the suit that be wearing that day"):
        assert p.is_dress_question(q.split()), q
    for q in ("can i wear sandals", "what is the haircut policy", "uniform for criminology"):
        assert not p.is_dress_question(q.split()), q
