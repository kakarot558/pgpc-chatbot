"""Phase 6 tests: data quality, predictions, thresholds and saved-model loading."""
import pandas as pd
import pytest

from app.services import intent_classifier as ic
from app.services.intent_classifier import (TEST_FILE, TRAIN_FILE, UNKNOWN, IntentClassifier, load_dataset)
from app.utils.text_cleaner import normalize_text


@pytest.fixture(scope="module")
def clf():
    return IntentClassifier.from_csv(min_confidence=0.35)


# ------------------------------------------------------------------ data files
def test_training_data_is_clean():
    df = pd.read_csv(TRAIN_FILE)
    assert list(df.columns) == ["text", "intent"]
    assert df.isna().sum().sum() == 0
    assert df["intent"].nunique() >= 12
    assert df["intent"].value_counts().min() >= 15, "every intent needs enough examples"


def test_no_question_has_two_labels():
    df = pd.read_csv(TRAIN_FILE)
    df["key"] = df["text"].map(normalize_text)
    conflicts = df.groupby("key")["intent"].nunique()
    assert conflicts.max() == 1, list(conflicts[conflicts > 1].index)


def test_test_set_does_not_leak_into_training():
    train = {normalize_text(t) for t in pd.read_csv(TRAIN_FILE)["text"]}
    test = {normalize_text(t) for t in pd.read_csv(TEST_FILE)["text"]}
    assert not (train & test)
    assert set(pd.read_csv(TEST_FILE)["intent"]) == set(pd.read_csv(TRAIN_FILE)["intent"])


# ------------------------------------------------------------------ predictions
@pytest.mark.parametrize("question, expected", [
    ("Hi, where can I find the registrar office in PGPC?", "office_location"),
    ("Where is Room 201?", "room_location"),
    ("Who is the registrar?", "employee_info"),
    ("What is the policy on attendance?", "handbook_policy"),
    ("How many BSCS students are there?", "enrollment_info"),
    ("What is the history of PGPC?", "school_history"),
    ("Hello po", "greeting"),
    ("Salamat po", "thanks"),
    ("Tell me a joke", "out_of_scope"),
])
def test_core_examples(clf, question, expected):
    assert clf.predict(question).intent == expected


def test_typos_still_work(clf):
    assert clf.predict("wher is the registrer ofice").intent == "office_location"


def test_result_has_confidence_and_top3(clf):
    r = clf.predict("Where is the cashier?")
    assert 0 <= r.confidence <= 1
    assert len(r.alternatives) == 3
    assert r.alternatives[0][0] == r.raw_intent
    assert r.alternatives == sorted(r.alternatives, key=lambda a: -a[1])


def test_empty_or_bad_input_is_unknown(clf):
    for bad in ["", "   ", "?!?!", None, 123]:
        r = clf.predict(bad)
        assert r.intent == UNKNOWN and r.confidence == 0.0


def test_low_confidence_becomes_unknown():
    strict = IntentClassifier.from_csv(min_confidence=0.999999)
    r = strict.predict("zzzz qqqq")
    assert r.intent == UNKNOWN
    assert r.raw_intent != UNKNOWN          # the best guess is still available for the logs


def test_routing_flags(clf):
    assert clf.predict("hello").is_small_talk
    assert clf.predict("what is the capital of france").is_out_of_scope
    r = clf.predict("where is the registrar office")
    assert r.needs_knowledge_search and not r.is_small_talk
    assert not clf.predict("thank you").needs_knowledge_search


def test_intent_does_not_depend_on_case_or_punctuation(clf):
    assert clf.predict("WHERE IS THE REGISTRAR OFFICE???").intent == clf.predict("where is the registrar office").intent


# ------------------------------------------------------------------ quality bar
def test_held_out_accuracy_is_reasonable(clf):
    df = pd.read_csv(TEST_FILE)
    pred = clf.predict_many(df["text"].tolist())
    accuracy = sum(p == t for p, t in zip(pred, df["intent"])) / len(df)
    assert accuracy >= 0.85, accuracy


# ------------------------------------------------------------------ saving / loading
def test_save_and_load_gives_same_answers(clf, tmp_path):
    path = clf.save(tmp_path / "m.joblib")
    loaded = IntentClassifier.load(path)
    for q in ["where is room 101", "who is the dean", "good morning"]:
        a, b = clf.predict(q), loaded.predict(q)
        assert (a.intent, a.confidence) == (b.intent, b.confidence)


def test_get_intent_classifier_trains_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "MODEL_FILE", tmp_path / "missing" / "intent_model.joblib")
    ic.get_intent_classifier.cache_clear()
    try:
        c = ic.get_intent_classifier()
        assert c.predict("where is the registrar office").intent == "office_location"
        assert (tmp_path / "missing" / "intent_model.joblib").exists()
    finally:
        ic.get_intent_classifier.cache_clear()


def test_load_dataset_normalizes():
    texts, labels = load_dataset()
    assert len(texts) == len(labels) > 500
    assert all(t == normalize_text(t) for t in texts[:50])
