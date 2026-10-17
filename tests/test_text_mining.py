import pytest

from app.services.text_mining import SpellingCorrector, TextMiner
from app.utils.text_cleaner import clean_user_input, normalize_text

# Two miners: one using NLTK data when present, one forced onto the built-in fallback lists.
@pytest.fixture(params=[True, False], ids=["nltk-if-available", "fallback"])
def miner(request):
    return TextMiner(use_nltk=request.param)


def test_spec_example_keywords(miner):
    r = miner.process("Hi, where can I find the registrar office in PGPC?")
    assert r.normalized == "hi where can i find the registrar office in pgpc"
    assert r.keywords == ["registrar", "office", "pgpc"]


def test_possessive_and_punctuation(miner):
    assert miner.process("What is PGPC's history?").keywords == ["pgpc", "history"]
    assert normalize_text("  Where's   the   LIBRARY??!! ") == "where the library"


def test_school_name_aliases_become_pgpc():
    assert normalize_text("Padre Garcia Polytechnic College") == "pgpc"
    assert normalize_text("P.G.P.C. handbook") == "pgpc handbook"


def test_accents_hyphens_and_numbers():
    assert normalize_text("Viñas, Niño") == "vinas nino"
    assert normalize_text("PGPC-CAT room T-101") == "pgpc cat room t 101"


@pytest.mark.parametrize("bad", ["", "   ", None, 123, "?!?!"])
def test_empty_or_non_text_input(miner, bad):
    r = miner.process(bad)
    assert r.tokens == [] and r.keywords == [] and r.search_text == ""


def test_control_characters_removed():
    assert clean_user_input("hello\x00 \x07world\n\n\tPGPC") == "hello world PGPC"


def test_very_long_input_is_processed_without_error(miner):
    r = miner.process("registrar " * 5000)
    assert r.keywords == ["registrar"]


def test_question_words_removed_but_negations_kept(miner):
    r = miner.process("Who is not allowed to enter the library?")
    assert "who" not in r.filtered_tokens and "is" not in r.filtered_tokens
    assert "not" in r.filtered_tokens


def test_lemmatization(miner):
    r = miner.process("facilities rules offices status address")
    assert r.lemmas == ["facility", "rule", "office", "status", "address"]


def test_lemmatization_can_be_switched_off():
    r = TextMiner(lemmatize=False, use_nltk=False).process("student rules")
    assert r.lemmas == ["student", "rules"]


def test_keywords_unique_and_ranked_by_frequency(miner):
    toks = ["library", "rule", "library", "book", "library", "rule"]
    assert miner.extract_keywords(toks) == ["library", "rule", "book"]
    assert miner.extract_keywords(toks, top_n=2, by_frequency=True) == ["library", "rule"]
    assert miner.document_keywords("Library library rules. Borrow a book from the library.", top_n=2)[0] == "library"


def test_tfidf_keywords_prefer_distinctive_words(miner):
    docs = ["The library opens early. Library books must be returned.",
            "The registrar issues transcripts. Registrar hours are posted.",
            "The clinic provides first aid."]
    out = miner.tfidf_keywords(docs, top_n=2)
    assert out[0][0] == "library" and out[1][0] == "registrar" and "clinic" in out[2]
    assert miner.tfidf_keywords([]) == [] and miner.tfidf_keywords(["", "?"]) == [[], []]


def test_spelling_corrector():
    sc = SpellingCorrector({"registrar", "library", "office", "pgpc", "handbook"}, cutoff=0.8)
    assert sc.correct(["registrer", "libary", "offce"]) == ["registrar", "library", "office"]
    assert sc.correct(["pgpc", "101", "abc", "banana"]) == ["pgpc", "101", "abc", "banana"]


def test_misspelled_question_end_to_end(miner):
    sc = miner.make_corrector({"registrar", "office", "pgpc"}, cutoff=0.8)
    r = miner.process("wher is the registrer ofice of pgpc", corrector=sc)
    assert r.lemmas == ["registrar", "office", "pgpc"]
    # without a corrector the typos stay as they are
    assert miner.process("registrer").lemmas == ["registrer"]


def test_say_is_chat_filler(miner):
    # "what does the handbook say about attendance" must keep only the meaningful words
    assert miner.process("What does the handbook say about attendance?").keywords == ["handbook", "attendance"]
