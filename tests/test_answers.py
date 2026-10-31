"""Phase 8 tests: how answers are written from retrieval results (no database needed)."""
from types import SimpleNamespace

from app.services.answer_generator import (INCOMPLETE_NOTE, LOW_CONFIDENCE_LEAD, NOT_FOUND, compose_answer,
                                            excerpt, tidy_text)
from app.services.retrieval import Hit, RetrievalResult


def intent(name, conf=0.9):
    return SimpleNamespace(intent=name, confidence=conf)


def hit(source_type, title, fields=None, content="", source="PGPC records", score=0.9, incomplete=False,
        coverage=1.0):
    return Hit(source_type, 1, title, content, source, score, score, coverage, [], incomplete, fields or {})


def result(*hits, found=True, confidence="high", intent_name=None):
    return RetrievalResult(question="q", keywords=[], intent=intent_name, hits=list(hits), found=found,
                           confidence=confidence, total_matches=len(hits), preferred_sources=[])


EMPTY = result(found=False, confidence="none")
OFFICE = {"name": "Registrar Office", "building": "Main Building", "floor": "1", "room_number": "102",
          "contact_number": "043-111-2222", "email": None, "about": None}


# ------------------------------------------------------------------ small talk and scope
def test_small_talk_never_needs_records():
    for name in ("greeting", "thanks", "goodbye", "bot_info"):
        a = compose_answer("hello", intent(name), EMPTY)
        assert a.kind == "small_talk" and a.text and a.pgpc_related is None and a.sources == []
    assert "PGPC SmartGuide" in compose_answer("hi", intent("greeting"), EMPTY).text


def test_bot_info_admits_its_limits():
    text = compose_answer("who are you", intent("bot_info"), EMPTY).text
    assert "instead of guessing" in text


def test_out_of_scope_is_declined_politely():
    a = compose_answer("tell me a joke", intent("out_of_scope"), EMPTY)
    assert a.kind == "out_of_scope" and a.pgpc_related is False and not a.found
    assert "PGPC" in a.text


def test_empty_question():
    assert compose_answer("   ", intent("unknown", 0.0), EMPTY).kind == "empty"


def test_not_found_says_so_and_never_guesses():
    a = compose_answer("where is the swimming pool", intent("facility_info"), EMPTY)
    assert a.kind == "not_found" and a.pgpc_related is True
    assert 'anything about "swimming pool"' in a.text and "check with the concerned PGPC office" in a.text
    assert a.sources == [] and a.confidence == "none"
    # no usable topic words: the general message
    assert compose_answer("how is it", intent("facility_info"), EMPTY).text == NOT_FOUND
    # an unclear question is not judged as PGPC-related or not
    assert compose_answer("asdf", intent("unknown", 0.1), EMPTY).pgpc_related is None


def test_hits_below_threshold_count_as_not_found():
    weak = result(hit("office", "Registrar Office", OFFICE, score=0.1), found=False, confidence="none")
    assert compose_answer("registrar", intent("office_location"), weak).kind == "not_found"


# ------------------------------------------------------------------ offices
def test_office_location_answer_with_source():
    a = compose_answer("Where is the registrar office?", intent("office_location"),
                       result(hit("office", "Registrar Office", OFFICE)))
    assert a.kind == "answer" and a.found and a.pgpc_related is True and not a.incomplete
    assert "The Registrar Office is located at: Floor 1, Main Building, Room 102." in a.text
    assert "043-111-2222" in a.text and a.text.endswith("Source: PGPC records")
    assert a.sources == [{"type": "office", "id": 1, "title": "Registrar Office", "source": "PGPC records"}]


def test_office_without_location_admits_it_and_keeps_what_it_knows():
    seeded = dict(OFFICE, building=None, floor=None, room_number=None, contact_number=None,
                  about="Students get forms here.")
    a = compose_answer("where is the registrar office", intent("office_location"),
                       result(hit("office", "Office of the Registrar", seeded, incomplete=True)))
    assert "I don't have the exact location of the Office of the Registrar yet." in a.text
    assert "Students get forms here." in a.text
    assert a.incomplete and "[ADMIN" not in a.text
    assert INCOMPLETE_NOTE not in a.text          # the text already said what is missing; no second warning


def test_office_contact_question_without_contact():
    o = dict(OFFICE, contact_number=None)
    a = compose_answer("what is the phone number of the registrar", intent("contact_info"),
                       result(hit("office", "Registrar Office", o)))
    assert "I don't have contact details for the Registrar Office yet." in a.text


def test_office_contact_question_with_contact_leads_with_it():
    a = compose_answer("registrar contact number", intent("contact_info"),
                       result(hit("office", "Registrar Office", OFFICE)))
    assert a.text.startswith("Contact details for the Registrar Office: Contact number: 043-111-2222.")


def test_generic_office_question_shows_description():
    o = dict(OFFICE, about="Keeps student records.")
    a = compose_answer("tell me about the registrar office", intent("faq_general"),
                       result(hit("office", "Registrar Office", o)))
    assert "Keeps student records." in a.text


# ------------------------------------------------------------------ facilities and rooms
CLINIC = {"name": "College Clinic", "building": None, "location": None, "equipment": None,
          "operating_hours": "Monday-Friday, 8 AM-5 PM", "about": "Provides first aid treatment."}


def test_facility_hours_answer():
    a = compose_answer("what time does the clinic open", intent("facility_info"),
                       result(hit("facility", "College Clinic", CLINIC, incomplete=True)))
    assert "The College Clinic is open Monday-Friday, 8 AM-5 PM." in a.text
    assert "I don't have" not in a.text
    assert INCOMPLETE_NOTE in a.text              # location is still missing, so the user is told to confirm


def test_facility_hours_missing():
    c = dict(CLINIC, operating_hours=None)
    a = compose_answer("clinic hours", intent("facility_info"), result(hit("facility", "College Clinic", c)))
    assert "I don't have the opening hours of the College Clinic yet." in a.text


def test_facility_location_missing_is_stated():
    a = compose_answer("where is the clinic", intent("room_location"),
                       result(hit("facility", "College Clinic", CLINIC, incomplete=True)))
    assert "I don't have the exact location of the College Clinic yet." in a.text


def test_room_answer():
    f = {"room_number": "201", "room_name": None, "building": "Annex", "floor": "2", "room_type": "Lecture room",
         "facility": None}
    a = compose_answer("where is room 201", intent("room_location"), result(hit("room", "Room 201", f)))
    assert "Room 201 is located at: Floor 2, Annex building." in a.text and "Type: Lecture room." in a.text


# ------------------------------------------------------------------ employees
def test_employee_with_only_a_name_does_not_invent_a_title():
    f = {"name": "Joy Hinanay Abu", "position": None, "office": None, "email": None, "contact_number": None}
    a = compose_answer("who is joy abu", intent("employee_info"),
                       result(hit("employee", "Joy Hinanay Abu", f, incomplete=True)))
    assert "Joy Hinanay Abu is listed in the PGPC employee records" in a.text
    assert "have not been added yet" in a.text and a.incomplete


def test_employee_with_details():
    f = {"name": "Maria Santos", "position": "College Registrar", "office": "Registrar Office",
         "email": "m@pgpc.edu", "contact_number": None}
    a = compose_answer("who is maria santos", intent("employee_info"), result(hit("employee", "Maria Santos", f)))
    assert "- Group / position: College Registrar" in a.text and "- Office: Registrar Office" in a.text
    assert "Contact number" not in a.text and not a.incomplete


def test_several_equal_matches_are_listed():
    f1 = {"name": "Joy Abu", "position": None, "office": None}
    f2 = {"name": "Joy Cruz", "position": "Faculty", "office": None}
    a = compose_answer("who is joy", intent("employee_info"),
                       result(hit("employee", "Joy Abu", f1, score=0.7), hit("employee", "Joy Cruz", f2, score=0.7)))
    assert a.kind == "list" and "- Joy Abu (details not added yet)" in a.text and "- Joy Cruz (Faculty)" in a.text
    assert len(a.sources) == 2 and "Source:" not in a.text


def test_a_clear_winner_is_not_listed():
    a = compose_answer("who is maria santos", intent("employee_info"),
                       result(hit("employee", "Maria Santos", {"name": "Maria Santos", "position": "Dean"}, score=0.9),
                              hit("employee", "Maria Cruz", {"name": "Maria Cruz"}, score=0.4)))
    assert a.kind == "answer" and "Maria Cruz" not in a.text


# ------------------------------------------------------------------ text records
HANDBOOK_TEXT = ("A student who is absent for more than twenty percent of the\nclass meetings shall be dropped "
                 "from the subject.\n1. Excused absences need valid\nproof.\n2. Tardiness is recorded.")


def test_handbook_answer_rejoins_wrapped_lines_and_cites_page():
    a = compose_answer("attendance policy", intent("handbook_policy"),
                       result(hit("handbook", "Section H - Absences", {}, HANDBOOK_TEXT, "PGPC Student Handbook, page 10")))
    assert 'Here is what I found under "Section H - Absences":' in a.text
    assert "twenty percent of the class meetings" in a.text
    assert "\n1. Excused absences need valid proof.\n2. Tardiness is recorded." in a.text
    assert a.text.endswith("Source: PGPC Student Handbook, page 10")


def test_long_text_is_cut_at_a_sentence_and_flagged():
    long = " ".join(f"Sentence number {i} says something useful." for i in range(60))
    a = compose_answer("policy", intent("handbook_policy"), result(hit("handbook", "Long", {}, long, "Handbook")))
    assert "..." in a.text and "only part of the text" in a.text and len(a.text) < 1100
    body, cut = excerpt(long)
    assert cut and body.endswith("...") and "Sentence number 59" not in body


def test_tidy_text_keeps_list_items_apart():
    assert tidy_text("Rules:\n1. One\ntwo\n2. Three") == "Rules:\n1. One two\n2. Three"
    assert tidy_text("a\n\nb") == "a\nb"
    assert tidy_text("") == ""


def test_faq_history_and_library():
    faq = compose_answer("how to request transcript", intent("faq_general"),
                         result(hit("faq", "How do I request a transcript?", {}, "Go to the registrar.", "PGPC FAQ")))
    assert faq.text.startswith("Go to the registrar.")
    his = compose_answer("when was pgpc founded", intent("school_history"),
                         result(hit("history", "Founding of PGPC", {"year": "2019"}, "Established by the town.")))
    assert his.text.startswith("Founding of PGPC (2019):")
    lib = compose_answer("is there a book on algorithms", intent("library_info"),
                         result(hit("library", "Introduction to Algorithms",
                                    {"author": "Cormen", "availability": "available", "location": None})))
    assert 'The library has "Introduction to Algorithms" by Cormen. Availability: available.' in lib.text


# ------------------------------------------------------------------ confidence
def test_low_confidence_is_presented_as_closest_match():
    weak = result(hit("office", "Registrar Office", OFFICE, score=0.4, coverage=0.5), confidence="low")
    a = compose_answer("something", intent("office_location"), weak)
    assert a.text.startswith(LOW_CONFIDENCE_LEAD) and a.confidence == "low"
    high = compose_answer("registrar", intent("office_location"), result(hit("office", "Registrar Office", OFFICE)))
    assert LOW_CONFIDENCE_LEAD not in high.text


def test_low_score_with_every_question_word_matched_gets_no_warning():
    full = result(hit("office", "Registrar Office", OFFICE, score=0.4, coverage=1.0), confidence="low")
    a = compose_answer("registrar office", intent("office_location"), full)
    assert LOW_CONFIDENCE_LEAD not in a.text and a.confidence == "low"


def test_as_dict_has_everything_the_api_returns():
    d = compose_answer("hi", intent("greeting"), EMPTY).as_dict()
    assert set(d) == {"answer", "kind", "found", "confidence", "intent", "pgpc_related", "incomplete", "sources",
                      "understood_as", "suggestions"}


# ------------------------------------------------------------------ Phase 9: office hours
def test_office_hours_question_says_hours_are_missing():
    a = compose_answer("what are the hours of Registrar Office", intent("office_location"),
                       result(hit("office", "Registrar Office", dict(OFFICE, room_number=None, building=None, floor=None))))
    assert "I don't have the office hours of the Registrar Office yet." in a.text
    assert "exact location" not in a.text
