"""Answer focusing: a long passage is cut down to the sentence(s) that answer the question."""
import re
from types import SimpleNamespace

from app.services.answer_generator import compose_answer
from app.services.focus import focus, split_units
from app.services.retrieval import Hit, RetrievalResult

STOP = set("a an the is are of for to from how what can do does i in at their with may must be many".split())


def lem(text):                                  # tiny stand-in lemmatizer so these tests need no NLTK data
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        if w.endswith("ed") and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


POLICY = ("PGPC Library Borrowing Policy\n"
          "Students may borrow up to three books at a time using their school identification card. "
          "Borrowed books must be returned within seven days. A fine of five pesos per day is charged "
          "for every overdue book. Reference books and theses cannot be taken out of the library.\n"
          "Lost books must be replaced with the same title or paid for at the current price. "
          "The librarian on duty will issue an official clearance after all books have been returned.")


def test_picks_the_sentence_that_answers():
    assert focus(POLICY, "how many books can a student borrow", lem)[0].startswith("Students may borrow up to three books")
    assert focus(POLICY, "what is the fine for an overdue book", lem)[0] == "A fine of five pesos per day is charged for every overdue book."


def test_short_or_unmatched_text_is_left_alone():
    assert focus("Short text. Two sentences.", "text", lem) is None
    assert focus(POLICY, "who is the dean", lem) is None


def test_list_items_keep_their_lead_in():
    text = ("Penalties for absence. " + "Filler sentence about nothing. " * 12 +
            "\nThe sanctions are:\n1. First offense: warning.\n2. Second offense: suspension.\n"
            "3. Third offense: dismissal.\n" + "More filler text here. " * 10)
    out = focus(text, "what are the sanctions for offense", lem)[0]
    assert out.startswith("The sanctions are:") and "2. Second offense: suspension." in out and "Filler" not in out


def test_numbers_and_titles_do_not_split_sentences():
    assert split_units("Dr. Cruz signed it. Next one.\n1. Item one.") == ["Dr. Cruz signed it.", "Next one.", "1. Item one."]


def test_compose_answer_uses_the_focused_sentence():
    h = Hit("document", 1, "Library Borrowing Policy", POLICY, "PGPC Library Manual", 0.9, 0.9, 1.0, [], False, {})
    r = RetrievalResult(question="q", keywords=[], intent=None, hits=[h], found=True, confidence="high",
                        total_matches=1, preferred_sources=[])
    a = compose_answer("what is the fine for an overdue book", SimpleNamespace(intent="library_info", confidence=0.9), r)
    assert "five pesos per day" in a.text and "librarian" not in a.text
    assert "best matches your question" in a.text and a.text.endswith("Source: PGPC Library Manual")
