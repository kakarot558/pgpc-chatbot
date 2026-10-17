"""Phase 9 tests: follow-up detection and rewriting (pure logic, no database)."""
from types import SimpleNamespace

import pytest

from app.services.followup import (MISS_TEXT, Topic, answer_with_context, detect_cue, detail_kind, rewrite)

REGISTRAR = Topic("office", 1, "Office of the Registrar")


# ------------------------------------------------------------------ cue detection
@pytest.mark.parametrize("q", ["what about its hours?", "Where is it?", "who is she", "what time does it open",
                               "what are their contact details", "what time does it close there"])
def test_pronoun_cues(q):
    assert detect_cue(q) == "pronoun"


@pytest.mark.parametrize("q", ["what about the library?", "how about the clinic", "and the contact number?",
                               "contact number?", "hours?", "what is the email"])
def test_weak_cues(q):
    assert detect_cue(q) == "weak"


@pytest.mark.parametrize("q", ["where is the registrar office", "is there a clinic", "are there any rooms",
                               "what does the handbook say about attendance", "hello", "who is abu", ""])
def test_not_followups(q):
    assert detect_cue(q) == "none"


def test_detail_kind():
    assert detail_kind("what about its hours") == "hours"
    assert detail_kind("what is its email") == "contact"
    assert detail_kind("where is it") == "location"
    assert detail_kind("who is the head of it") is None


# ------------------------------------------------------------------ rewriting
def test_rewrite_detail_requests_become_clean_questions():
    assert rewrite("what about its hours?", REGISTRAR) == "what are the hours of Office of the Registrar"
    assert rewrite("what is its email", REGISTRAR) == "what is the contact number of Office of the Registrar"
    assert rewrite("where is it", REGISTRAR) == "where is Office of the Registrar"


def test_rewrite_substitutes_other_pronouns_and_attaches_weak_topics():
    assert rewrite("who is the head of it", REGISTRAR) == "who is the head of Office of the Registrar"
    assert rewrite("what about the policies", REGISTRAR, "weak") == "the policies Office of the Registrar"


# ------------------------------------------------------------------ the decision (with fake pipeline pieces)
def ans(found=True, kind="answer", sources=(), text="x"):
    return SimpleNamespace(found=found, kind=kind, sources=list(sources), text=text)


def src(t, i):
    return {"type": t, "id": i, "title": "t"}


def run(question, topic, answers, intent="office_location"):
    """`answers` maps a question to the fake Answer it produces. Records which questions were asked."""
    asked = []

    def answer_fn(q):
        asked.append(q)
        return answers.get(q, ans(found=False, kind="not_found"))

    miss = lambda text: ans(found=False, kind="not_found", text=text)
    result = run.out = answer_with_context(question, topic, answer_fn, lambda q: intent, miss)
    return result, asked


def test_no_topic_means_no_rewrite():
    (a, via), asked = run("what about its hours", None, {"what about its hours": ans(False, "not_found")})
    assert via is None and asked == ["what about its hours"]


def test_pronoun_follow_up_is_rewritten_and_stays_on_topic():
    good = ans(sources=[src("office", 1)], text="no hours yet")
    (a, via), asked = run("what about its hours?", REGISTRAR,
                          {"what are the hours of Office of the Registrar": good})
    assert a is good and via == "what are the hours of Office of the Registrar"


def test_pronoun_follow_up_never_drifts_to_another_record():
    clinic = ans(sources=[src("facility", 7)], text="clinic hours")
    (a, via), _ = run("what about its hours?", REGISTRAR,
                      {"what are the hours of Office of the Registrar": clinic, "what about its hours?": clinic})
    assert not a.found and "Office of the Registrar" in a.text


def test_pronoun_in_a_handbook_question_is_answered_as_it_stands():
    handbook = ans(sources=[src("handbook", 3)])
    (a, via), _ = run("is it okay to be late", REGISTRAR, {"is it okay to be late": handbook})
    assert a is handbook and via is None


def test_weak_cue_naming_a_new_record_keeps_the_new_record():
    library = ans(sources=[src("facility", 2)])
    (a, via), asked = run("what about the library?", REGISTRAR, {"what about the library?": library})
    assert a is library and via is None and len(asked) == 1


def test_weak_cue_without_an_entity_uses_the_topic():
    good = ans(sources=[src("office", 1)])
    (a, via), _ = run("contact number?", REGISTRAR,
                      {"contact number?": ans(sources=[src("handbook", 9)]),
                       "what is the contact number of Office of the Registrar": good})
    assert a is good and via == "what is the contact number of Office of the Registrar"


def test_small_talk_and_other_topics_are_never_rewritten():
    (a, via), asked = run("thanks, it was helpful", REGISTRAR, {}, intent="thanks")
    assert via is None and asked == ["thanks, it was helpful"]


def test_handbook_topic_accepts_any_found_answer():
    topic = Topic("handbook", 4, "Attendance")
    good = ans(sources=[src("handbook", 5)])
    (a, via), _ = run("what about the penalties", topic, {"what about the penalties": ans(False, "not_found"),
                                                          "penalties for Attendance": good}, intent="handbook_policy")
    assert a is good and via == "penalties for Attendance"
