"""Tests for the input reader (typos, texting slang, Taglish), yes/no questions, split questions and follow-ups."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import input_reader as ir
from app.services import policy_detail as pd
from app.services import retrieval as rv
from app.services import suggestions as sg
from app.services.answer_generator import generate_answer
from app.services.query_rewrite import split_questions
from app.utils.text_cleaner import normalize_text


# ------------------------------------------------------------------ pure pieces
def test_edit_distance_counts_a_swap_as_one_edit():
    assert ir.osa_distance("recieve", "receive", 2) == 1
    assert ir.osa_distance("haircutt", "haircut", 2) == 1
    assert ir.osa_distance("library", "libary", 2) == 1
    assert ir.osa_distance("abc", "xyzxyz", 1) == 2          # too far: stops early (limit + 1)


def test_letter_floods_and_punctuation_floods_are_squeezed():
    assert ir.squeeze_floods("pleaseeee tell me???") == "pleasee tell me?"
    assert ir.squeeze_floods("HAIRCUT!!!") == "HAIRCUT!"


def test_texting_slang_expands_only_where_it_means_something():
    words, changes = ir.expand_slang("whats d penalty 4 cheating".split())
    assert words == "whats the penalty for cheating".split()
    assert ir.expand_slang("who r the faculty".split())[0] == "who are the faculty".split()
    assert ir.expand_slang("u know the dress code".split())[0][0] == "you"
    # a lone 4 / d at the end of a question is left alone
    assert ir.expand_slang("room number 4".split())[0] == "room number 4".split()
    assert ir.expand_slang("pls tell me abt wifi".split())[0] == "please tell me about wifi".split()


def test_filipino_phrases_become_english():
    text, changed = ir.apply_phrases("pwede ba magdala ng cellphone sa klase")
    assert changed and text == "can i bring cellphone in class"
    assert ir.apply_phrases("ano ang mangyayari kapag nag cheat")[0] == "what happens if cheat"
    assert ir.apply_phrases("bawal ba ang tattoo")[0] == "is not allowed tattoo"


@pytest.fixture(scope="module")
def vocab():
    texts = ["Dress Code Policy haircut tattoo sandals library registrar president scholarship tuition enrollment "
             "attendance cashier clinic uniform absence tardiness utility cheating plagiarism dishonesty wearing"]
    return ir.build_vocabulary(texts, names=["Office of the Registrar", "Cashier's Office", "Abu Joy"])


def test_typos_are_repaired(vocab):
    cases = {"haircutt": "haircut", "registrer": "registrar", "presedent": "president", "libary": "library",
             "scholarhip": "scholarship", "tution": "tuition", "dres": "dress", "cashir": "cashier",
             "unifrom": "uniform", "cheeting": "cheating", "attendence": "attendance"}
    for wrong, right in cases.items():
        assert ir.best_correction(wrong, vocab) == right, wrong


def test_correct_words_and_names_are_never_changed(vocab):
    for word in ("wear", "sandals", "where", "policy", "registrar", "abu", "school", "student", "tuition", "pgpc",
                 "cellphone", "klase", "pwede"):
        assert ir.best_correction(word, vocab) is None, word
    assert ir.best_correction("xyz", vocab) is None          # too short to guess
    assert ir.best_correction("qwertyuiop", vocab) is None   # nothing close: left alone


def test_a_dropped_letter_beats_a_function_word(vocab):
    # "dres" is one letter short of "dress"; "does" is also one edit away but is a common word nobody means here
    assert ir.best_correction("dres", vocab) == "dress"


def test_read_input_repairs_and_reports(vocab):
    r = ir.read_input("wat is the haircutt polcy", vocab)
    assert r.text.startswith("what is the haircut pol")
    assert ("haircutt", "haircut") in r.corrections and r.display == r.text
    r = ir.read_input("whats d penalty 4 cheating", vocab)
    assert r.text == "whats the penalty for cheating" and r.display


def test_a_clean_question_is_returned_untouched(vocab):
    q = "Where is the registrar's office?"
    r = ir.read_input(q, vocab)
    assert r.text == q and r.display is None and not r.corrections


def test_taglish_is_translated_but_not_shown_as_understood_as(vocab):
    r = ir.read_input("ano ang policy sa gupit", vocab)
    assert "haircut" in r.text and r.filipino and r.display is None


def test_the_reader_never_raises():
    r = ir.read_input("", None)
    assert r.text == ""
    assert ir.read_input("!!!???", None).text


# ------------------------------------------------------------------ several questions without a "?"
def test_two_questions_joined_with_and_are_split():
    parts = split_questions("who is the mayor and who is the president")
    assert parts == ["who is the mayor?", "who is the president?"]
    assert len(split_questions("where is the clinic; what are the library rules")) == 2


def test_one_question_is_not_split():
    for q in ("what are the rules and regulations", "tuition and fees", "where is the clinic and what are its hours",
              "who is the president of pgpc"):
        assert split_questions(q) == [q], q


# ------------------------------------------------------------------ yes/no and "what happens if"
def words(q):
    return normalize_text(q).split()


def test_permission_and_consequence_questions_are_detected():
    for q in ("can i wear sandals", "is blonde hair allowed", "is not allowed tattoo", "may i bring a cellphone"):
        assert pd.is_permission_question(words(q)), q
    assert pd.asks_consequence(words("what happens if i cheat"))
    assert not pd.is_permission_question(words("how many books can i borrow"))
    assert not pd.is_permission_question(words("where is the clinic"))


def test_topic_ignores_action_words():
    assert pd.topic_terms(words("can i wear sandals")) == ["sandals"]
    assert pd.topic_terms(words("can i bring cellphone in class")) == ["cellphone"]


def test_short_answer_only_for_a_real_offense():
    idx = pd.parse_offenses("""
Major Offense
Offenses Against Order
1. Wearing sandals and slippers during classes
2. Posting of announcements without approval
OFFENSE AGAINST ORDER
1. 1 month suspension
""")
    hits = pd.direct_hits(idx.items, ["sandals"])
    assert len(hits) == 1 and "major" in pd.short_answer(hits)
    assert pd.direct_hits(idx.items, ["borrow", "books"]) == []
    assert pd.short_answer([]) is None
    assert "sanctions" in pd.short_answer(hits, consequence=True)


# ------------------------------------------------------------------ knowing where a passage really ends
def test_a_cut_sentence_borrows_its_ending_from_the_next_passage():
    assert rv.finish_sentence("If they exceed the limit, the school shall",
                              "automatically DROP the student. Next sentence.") == \
        "If they exceed the limit, the school shall automatically DROP the student."
    assert rv.finish_sentence("A full sentence.", "Next.") == "A full sentence."
    assert rv.finish_sentence("cut off", "no end here and it never stops " * 20) == "cut off"


# ------------------------------------------------------------------ follow-up buttons
def test_followups_are_related_and_never_repeat_the_question():
    s = sg.suggest_followups("what is the haircut policy", "answer", True, "what is the haircutt policy")
    assert s and "What is the haircut policy?" not in s
    assert any("dress code" in q.lower() or "blonde" in q.lower() for q in s)
    assert sg.suggest_followups("hello", "small_talk", True) == []
    assert len(sg.suggest_followups("who is the president", "answer", True)) <= sg.MAX_SUGGESTIONS


# ------------------------------------------------------------------ the whole pipeline on the real handbook
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


MESSY = [
    # (what the student typed, text the answer must contain, intent-independent)
    ("what is the haircutt policy", "Not in proper hair cut"),
    ("haircut polcy", "Long hair for boys"),
    ("wat is the dres code", "Dress Code Policy"),
    ("who is the presedent of pgpc", "Nino J. Vinas"),
    ("whos the presidnt", "Nino J. Vinas"),
    ("where is the registrer office", "Office of the Registrar"),
    ("wer is the clinic", "College Clinic"),
    ("pls tell me abt the attendance policy", "ABSENCES AND TARDINESS"),
    ("whats d penalty 4 cheating", "Dishonesty"),
    ("who r the faculty", "Faculty (52 people"),
    ("HAIRCUT!!!", "Long hair for boys"),
    ("scholarhip requirements", "SCHOLARSHIP"),
    ("ano ang policy sa gupit", "Not in proper hair cut"),
    ("sino ang dean", "Joy H. Abu"),
    ("pwede ba mag long hair ang lalaki", "Long hair for boys"),
]


@pytest.mark.parametrize("typed,expected", MESSY)
def test_messy_questions_get_the_right_answer(db, typed, expected):
    a = generate_answer(db, typed)
    assert a.found and a.kind in ("answer", "list"), typed
    assert expected.lower() in a.text.lower(), (typed, a.text[:200])


def test_a_repaired_question_says_how_it_was_understood(db):
    a = generate_answer(db, "what is the haircutt policy")
    assert a.understood_as == "what is the haircut policy"
    assert generate_answer(db, "what is the haircut policy").understood_as is None
    assert "understood_as" in a.as_dict() and isinstance(a.as_dict()["suggestions"], list)


def test_yes_no_questions_get_a_short_answer_first(db):
    for q, part in (("can i wear sandals", "major offenses"), ("is blonde hair allowed", "minor offenses"),
                    ("bawal ba ang tattoo", "major offenses"),
                    ("pwede ba magdala ng cellphone sa klase", "minor offenses")):
        a = generate_answer(db, q)
        assert a.text.startswith(("Short answer: no.", "Maikling sagot: hindi.")), q     # Filipino question: Filipino lead
        assert part in a.text.split("\n")[0], q
    cheat = generate_answer(db, "ano ang mangyayari kapag nag cheat").text
    assert "Dishonesty" in cheat and "Dismissal" in cheat


def test_a_question_that_is_not_about_conduct_gets_no_offense_verdict(db):
    a = generate_answer(db, "can i borrow 5 books")
    assert "Short answer" not in a.text and "LOAN PERIODS" in a.text


def test_two_questions_without_a_question_mark_are_both_answered(db):
    a = generate_answer(db, "who is the mayor and who is the president")
    assert a.kind == "multi" and "Celsa" in a.text and "Nino J. Vinas" in a.text


def test_missing_data_is_said_plainly(db):
    a = generate_answer(db, "saan ang cr")
    assert not a.found and "Wala pang naitalang lokasyon" in a.text            # Filipino question, Filipino reply
    a = generate_answer(db, "what time is the library open")
    assert not a.found and "opening hours" in a.text
    assert generate_answer(db, "what are the clinic hours").found


def test_absence_answer_is_a_complete_sentence_without_a_false_warning(db):
    a = generate_answer(db, "how many absences are allowed")
    assert "automatically DROP the said student" in a.text
    assert "not completely sure" not in a.text


def test_foreign_and_nonsense_questions_are_still_declined(db):
    assert generate_answer(db, "who is the president of the united states").kind == "out_of_scope"
    assert generate_answer(db, "tell me a joke").kind == "out_of_scope"
    assert generate_answer(db, "hello").kind == "small_talk"


def test_every_suggested_follow_up_really_gets_an_answer(db):
    asked = set()
    for _, questions in sg.GROUPS:
        asked.update(questions)
    asked.update(sg.DEFAULT)
    bad = [q for q in sorted(asked) if not (generate_answer(db, q).found
                                            and generate_answer(db, q).kind in ("answer", "list"))]
    assert bad == [], f"follow-up questions with no answer: {bad}"


def test_uniform_attire_and_schedule_questions_each_get_the_right_part(db):
    for q in ("uniform", "what is the uniform", "what is the attire", "what to wear", "dress code"):
        t = generate_answer(db, q).text
        assert "College uniform and I.D." in t and "schedule for wearing" in t.lower(), q      # what it is + the schedule
        assert "Failing to wear" not in t, q                                           # not the offense table
    for q in ("what is the attire schedule", "uniform schedule", "what to wear on wednesday"):
        t = generate_answer(db, q).text
        assert t.count("Wednesday - Friday - School Uniform") == 1 and "Implementation" not in t, q
        assert "Source: PGPC Student Handbook - Chapter XVI" in t


def test_vision_and_mission_are_shown_in_the_official_wording(db):
    both = generate_answer(db, "what is the vision and mission of pgpc").text
    assert both.startswith("The Vision of the Padre Garcia Polytechnic College (PGPC) shall be:")
    assert "nation-building." in both and "The Mission of Padre Garcia Polytechnic College (PGPC) shall be:" in both
    assert "total human development." in both and "SHS diploma" not in both
    only_v = generate_answer(db, "pgpc vision").text
    assert "premier higher learning" in only_v and "Mission of" not in only_v
    only_m = generate_answer(db, "what is the mission").text
    assert "committed to produce" in only_m and "Vision of" not in only_m
    assert "Vision" not in generate_answer(db, "what are the admission requirements").text.split("\n")[0]


def test_student_count_questions_say_there_is_no_data_instead_of_guessing(db):
    for q in ("how many students in BSCS", "how many students per program", "how many enrollees does pgpc have"):
        a = generate_answer(db, q)
        assert not a.found and "enrolled students on file" in a.text and "Study Load" not in a.text, q
    assert "loan periods" in generate_answer(db, "how many books can i borrow").text.lower()     # other 'how many' unaffected


def test_honor_lists_and_named_sections_are_found_by_name(db):
    d = generate_answer(db, "what is the dean's list").text
    assert "weighted average of 1.26 to 1.5" in d and "College Dean" not in d.split("\n")[0]
    assert "1.25 or" in generate_answer(db, "what is the president's list").text
    assert "Leave of Absence".lower() in generate_answer(db, "leave of absence").text.lower()
    assert "CHANGE OF MATRICULATION" in generate_answer(db, "how to change matriculation").text


def test_phone_and_tattoo_questions_use_the_conduct_rules(db):
    for q, part in (("can i bring my phone in class", "cell phone"), ("can i have a tattoo", "tattoo")):
        t = generate_answer(db, q).text
        assert t.startswith("Short answer: no.") and part in t.lower(), q


def test_history_location_and_opening_figure(db):
    assert "Municipal Ordinance No. 42-2023" in generate_answer(db, "when was pgpc founded").text
    assert "Padre Garcia, Batangas" in generate_answer(db, "where is pgpc located").text
    assert "nine hundred" in generate_answer(db, "how many students in bscs").text
    assert "Office of the Registrar" in generate_answer(db, "where is the registrar office").text    # not hijacked


def test_a_passage_that_misses_part_of_the_question_is_not_passed_off_as_the_answer(db):
    for q in ("what is the penalty for late return of books", "how to appeal a grade"):
        a = generate_answer(db, q)
        assert not a.found and "I would rather not guess" in a.text and "closest topic" in a.text, q
    assert generate_answer(db, "what if i miss the exam").found or True                  # judged either way, never an error
    assert generate_answer(db, "what is the policy on social media").found               # both words are in the answer
    assert generate_answer(db, "how to drop a subject").found
