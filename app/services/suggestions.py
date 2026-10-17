"""Follow-up question suggestions shown as buttons under an answer.

A student who just read the haircut rules probably wants the dress code or the sanctions next. Each group below
lists topic words and questions that the chatbot answers well (tests/test_input_reading.py checks that every
question here really gets an answer from the handbook). Add a group when you see a common follow-up in the chat logs.

Pure functions, no database.
"""
import re

from app.utils.text_cleaner import normalize_text

MAX_SUGGESTIONS = 3

# (topic words in the question, follow-up questions)
GROUPS: list[tuple[set[str], list[str]]] = [
    ({"hair", "haircut", "blonde", "tattoo", "earring", "earing", "grooming", "sandal", "slipper", "sandals", "slippers"},
     ["What is the dress code policy?", "Is blonde hair allowed?", "Can I wear sandals?", "What are the major offenses?"]),
    ({"dress", "uniform", "attire", "washday", "washdays"},
     ["What is the haircut policy?", "Can I wear sandals?", "What are the major offenses?"]),
    ({"absence", "absences", "absent", "attendance", "tardiness", "tardy", "late"},
     ["How many absences are allowed?", "How do I get an excuse slip?", "What happens if I am late?"]),
    ({"cheat", "cheating", "dishonesty", "plagiarism", "copying"},
     ["What are the major offenses?", "What is the attendance policy?", "What are the sanctions for minor offenses?"]),
    ({"offense", "offenses", "sanction", "sanctions", "penalty", "violation", "violations", "minor", "major"},
     ["What is the haircut policy?", "What happens if I cheat?", "Can I wear sandals?"]),
    ({"cellphone", "gadget", "phone"},
     ["What are the minor offenses?", "What is the internet usage policy?", "What happens if I cheat?"]),
    ({"enroll", "enrollment", "enrol", "registration", "register", "matriculation", "admission"},
     ["What are the requirements for enrollment?", "How do I drop a subject?", "What scholarships are available?"]),
    ({"drop", "dropping", "withdraw", "shift", "shifting", "transfer"},
     ["How do I enroll?", "How do I shift to another course?", "What is the attendance policy?"]),
    ({"library", "borrow", "book", "books", "loan", "circulation"},
     ["How many books can I borrow?", "What are the library rules?", "What is the internet usage policy?"]),
    ({"scholarship", "scholarships", "financial", "assistance", "grant"},
     ["What scholarships are available?", "How do I enroll?", "What is the grading system?"]),
    ({"grade", "grades", "grading", "gwa", "honor", "honors", "graduation", "graduate", "graduating"},
     ["What is the grading system?", "What are the honors for graduation?", "What are the requirements for graduation?"]),
    ({"president", "mayor", "dean", "trustee", "trustees", "vice", "official", "officials", "board"},
     ["Who is the president of PGPC?", "Who are the Board of Trustees?", "Who is the college dean?"]),
    ({"faculty", "teacher", "teachers", "professor", "employee", "employees", "personnel", "staff", "guard"},
     ["Who are the faculty?", "Who are the administrative personnel?", "Who is the president of PGPC?"]),
    ({"clinic", "registrar", "cashier", "office", "guidance", "osa", "saco"},
     ["What are the clinic hours?", "Where is the registrar's office?", "Where can I pay?"]),
    ({"internet", "wifi", "network"},
     ["What is the policy on cellphone use?", "What are the library rules?", "What are the minor offenses?"]),
    ({"ojt", "practicum", "internship", "training"},
     ["What is the OJT policy?", "What is the attendance policy?", "What are the requirements for graduation?"]),
    ({"organization", "organizations", "council", "csg", "student"},
     ["What is the policy on student organizations?", "What are the clinic hours?", "What is the dress code policy?"]),
]
DEFAULT = ["What is the dress code policy?", "How do I enroll?", "Who is the president of PGPC?"]
# Replies that need no follow-up buttons.
QUIET_KINDS = {"small_talk", "out_of_scope", "empty", "multi"}


def _norm(q: str) -> str:
    return " ".join(normalize_text(q).split())


def suggest_followups(question: str, kind: str, found: bool, asked: str | None = None) -> list[str]:
    """Up to MAX_SUGGESTIONS questions related to what was just asked. `question` is the repaired English question.
    Never repeats the question that was just asked."""
    if kind in QUIET_KINDS:
        return []
    words = set(_norm(question).split())
    asked_norm = {_norm(question)} | ({_norm(asked)} if asked else set())
    scored = []
    for order, (topic, questions) in enumerate(GROUPS):
        hit = len(words & topic)
        if hit:
            scored.append((-hit, order, questions))
    scored.sort()
    pool: list[str] = []
    for _, _, questions in scored[:2]:
        pool += questions
    if not pool:
        pool = DEFAULT if not found else []
    out, seen = [], set()
    for q in pool:
        n = _norm(q)
        # skip the question just asked, and near copies of it ("what is the dress code policy" ~ "dress code")
        if n in seen or n in asked_norm or any(n == a or (len(a.split()) >= 4 and (n in a or a in n)) for a in asked_norm):
            continue
        seen.add(n)
        out.append(q)
        if len(out) == MAX_SUGGESTIONS:
            break
    return out
