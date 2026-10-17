"""Understanding more questions: Taglish, several questions in one message, and 'closest topics' on a miss."""
from types import SimpleNamespace

from app.services.answer_generator import (NOT_FOUND, SUGGEST_LEAD, Answer, combine_answers, compose_answer,
                                           suggestions)
from app.services.focus import focus
from app.services.query_rewrite import is_overview, split_questions, to_english
from app.services.retrieval import find_heading
from app.services.retrieval import Hit, RetrievalResult


# ------------------------------------------------------------------ Taglish
def test_filipino_question_words_become_english():
    assert to_english("Saan po ang registrar office?") == "where registrar office"
    assert to_english("Magkano po ang tuition?") == "how much tuition"
    assert "borrow" in to_english("Pwede ba humiram ng libro sa library?").split()


def test_english_questions_are_never_changed():
    for q in ("Where is the registrar's office?", "May I borrow a book?", "What are the clinic hours?"):
        assert to_english(q) == q


# ------------------------------------------------------------------ several questions
def test_two_real_questions_are_split():
    assert split_questions("Where is the clinic? What are its hours?") == ["Where is the clinic?", "What are its hours?"]


def test_short_follow_ups_and_single_questions_stay_whole():
    for q in ("contact number?", "Where is the clinic? hours?", "Where is the clinic?", "hello"):
        assert split_questions(q) == [q]


def test_combine_answers_numbers_each_question():
    a1 = Answer("The clinic is in Main Building.", "answer", "facility_info", 0.9, True, "high", True,
                sources=[{"type": "facility", "id": 1, "title": "Clinic", "source": "PGPC facility records"}])
    a2 = Answer("I couldn't find that.", "not_found", "unknown", 0.0, False, "none", True)
    both = combine_answers([("Where is the clinic?", a1), ("What is the dress code?", a2)])
    assert both.kind == "multi" and both.found and len(both.sources) == 1
    assert "1) Where is the clinic?" in both.text and "2) What is the dress code?" in both.text


# ------------------------------------------------------------------ closest topics on a miss
def hit(source_type, title, score):
    return Hit(source_type, 1, title, "text", "src", score, score, 0.5, [], False, {})


def miss(*hits):
    return RetrievalResult(question="q", keywords=[], intent=None, hits=list(hits), found=False, confidence="none",
                           total_matches=0, preferred_sources=[])


def test_a_miss_with_close_topics_suggests_them():
    r = miss(hit("handbook", "Section H - Absences", 0.3), hit("faq", "How do I enroll?", 0.2), hit("handbook", "Section H - Absences", 0.2))
    a = compose_answer("what about attendence", SimpleNamespace(intent="handbook_policy", confidence=0.9), r)
    assert a.kind == "not_found" and not a.found and a.text.startswith(SUGGEST_LEAD)
    assert a.text.count("Section H - Absences") == 1 and "How do I enroll?" in a.text


def test_weak_or_person_matches_are_not_suggested():
    assert suggestions(miss(hit("handbook", "Tiny", 0.05), hit("employee", "Maria Santos", 0.3))) == []
    a = compose_answer("where is the pool", SimpleNamespace(intent="facility_info", confidence=0.9), miss())
    assert 'anything about "pool"' in a.text and SUGGEST_LEAD not in a.text


def test_a_suggestion_must_really_overlap_the_question():
    weak = Hit("handbook", 1, "Section E - Consent of Instructor", "text", "src", 0.3, 0.3, 0.2, [], False, {})
    assert suggestions(miss(weak)) == []


def test_missing_person_or_position_is_not_answered_with_handbook_topics():
    from app.services.answer_generator import NO_PERSON
    r = miss(hit("handbook", "Section E - Consent of Instructor", 0.4))
    a = compose_answer("who is the program chair of bscs", SimpleNamespace(intent="employee_info", confidence=0.9), r)
    assert a.text == NO_PERSON and not a.found


# ------------------------------------------------------------------ broad questions
def test_broad_policy_questions_are_overview_questions():
    for q in ("what are the policies in PGPC", "What does the handbook cover?", "list the rules"):
        assert is_overview(q), q
    for q in ("policy for haircut", "what does the handbook say about attendance", "how do I enroll", "hello"):
        assert not is_overview(q), q


# ------------------------------------------------------------------ headings and procedures
def test_heading_inside_a_passage_is_found():
    assert find_heading("text\n4. Section B - Pre-Enrollment Requirements and Procedure\nNew Students") == \
        "Section B - Pre-Enrollment Requirements and Procedure"
    assert find_heading("no heading here") is None


PROCEDURE = ("Continuing students must bring their clearance. " * 4 + "\nFor Old Students:\n"
             "1. Present the clearance to the Registrar.\n2. Submit your class cards to the program chair.\n"
             "3. Pay your fees at the cashier.\n4. Have your form stamped ENROLLED.\n"
             "Note: procedures may change. " * 3)


def test_how_do_i_question_gets_every_step():
    out = focus(PROCEDURE, "how do i enroll stamped", lambda t: [w for w in __import__("re").findall(r"[a-z]+", t.lower()) if len(w) > 3],
                {}, whole_list=True)[0]
    assert out.startswith("For Old Students:") and "1. Present" in out and "3. Pay your fees" in out and "4. Have" in out


def test_pdf_noise_lines_are_dropped():
    from app.services.answer_generator import tidy_text
    assert tidy_text("Step one\n----\npage 7\nstep two") == "Step one step two"
    hit_ = Hit("handbook", 1, "Section A", "Intro text.\n----\nMore text.", "Handbook", 0.9, 0.9, 1.0, [], False,
               {"heading": "Section B - Pre-Enrollment Requirements and Procedure"})
    r = RetrievalResult(question="q", keywords=[], intent=None, hits=[hit_], found=True, confidence="high",
                        total_matches=1, preferred_sources=[])
    text = compose_answer("enrollment", SimpleNamespace(intent="enrollment_info", confidence=0.9), r).text
    assert "----" not in text and 'under "Section B - Pre-Enrollment Requirements and Procedure"' in text
