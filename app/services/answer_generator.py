"""Phase 8: answer generation.

Turns what Phase 6 (intent) and Phase 7 (retrieval) found into a reply a student can read.

    question -> intent classifier -> retrieval -> compose_answer() -> Answer

There is NO language model in this step. Every sentence is built from a stored PGPC record or from
a fixed template, so the chatbot cannot invent an office location, a phone number or a policy.

Honesty rules (the same ones Phase 7 prepared for):
  * Nothing found above the similarity threshold  -> say so, never guess.
  * A record with a missing detail (no room number, no contact...) -> say that detail "has not been added yet".
  * Low confidence -> the answer is introduced as "the closest match", not as a fact.
  * Greetings, thanks and goodbyes never search the knowledge base; off-topic questions are politely declined.
  * "[ADMIN: ...]" placeholders never reach the user (Phase 7 already strips them).

Try it:  python -m app.services.answer_generator "Where is the registrar office?"
"""
import logging
import re
import sys
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.policy_detail import asked_for_everything, is_topic_only, wants_full_detail
from app.services.retrieval import Hit, RetrievalResult, retrieve
from app.utils.text_cleaner import clean_user_input, normalize_text

# --------------------------------------------------------------------------- fixed replies
EXAMPLES = [
    "Where is the registrar's office?",
    "What are the clinic hours?",
    "What does the handbook say about attendance?",
]

GREETING = ("Hello! I'm PGPC SmartGuide, the information assistant of Padre Garcia Polytechnic College (PGPC). "
            "You can ask me about PGPC offices, facilities, rooms, employees, the student handbook, school history "
            "and the library. What would you like to know?")
THANKS = "You're welcome! Feel free to ask anything else about PGPC."
GOODBYE = "Goodbye! Come back anytime you have a question about PGPC."
BOT_INFO = ("I'm PGPC SmartGuide. I answer questions about Padre Garcia Polytechnic College using only the records "
            "PGPC has added to my knowledge base: the student handbook, offices, facilities, rooms, employees, "
            "school history, library and FAQs. If I don't have a record for something, I'll tell you instead of "
            "guessing, so please confirm important details with the concerned PGPC office.")
OUT_OF_SCOPE = ("I can only help with questions about PGPC (Padre Garcia Polytechnic College), so I can't answer "
                "that one. You could ask me, for example: " + "; ".join(f'"{e}"' for e in EXAMPLES) + ".")
EMPTY = "Please type a question about PGPC and I'll do my best to help."
NOT_FOUND = ("I'm sorry, I couldn't find information about that in the PGPC knowledge base. It may not have been "
             "added yet. Try asking with specific words (an office name, a person's name or a handbook topic), "
             "or check with the concerned PGPC office. For example: " + "; ".join(f'"{e}"' for e in EXAMPLES) + ".")
LOW_CONFIDENCE_LEAD = "I'm not completely sure this is what you meant, but this is the closest match I found:"
INCOMPLETE_NOTE = ("Note: some details for this record have not been added yet, so please confirm with the "
                   "concerned PGPC office.")

SMALL_TALK = {"greeting": GREETING, "thanks": THANKS, "goodbye": GOODBYE, "bot_info": BOT_INFO}

MAX_EXCERPT_CHARS = 700
MAX_DETAIL_CHARS = 2500      # "tell me the details / policy ..." gets the whole passage, not one sentence of it
MAX_LIST_ITEMS = 5
LIST_SCORE_RATIO = 0.85      # records scoring within 15% of the best one count as "equally good matches"
FULL_COVERAGE = 0.95
LISTABLE = {"employee", "office", "facility", "room", "library", "position"}

# Words in the question that tell us which detail the student wants first.
WANT_LOCATION = {"where", "located", "location", "find", "directions", "building", "floor", "way"}
WANT_CONTACT = {"contact", "phone", "telephone", "number", "email", "mail", "call", "reach", "hotline"}
WANT_HOURS = {"hours", "hour", "open", "opens", "close", "closes", "schedule", "time", "when"}


# --------------------------------------------------------------------------- result object
@dataclass
class Answer:
    text: str
    kind: str                     # small_talk | out_of_scope | empty | answer | list | not_found
    intent: str
    intent_confidence: float
    found: bool
    confidence: str               # high | medium | low | none
    pgpc_related: bool | None     # None = cannot tell (small talk, unclear question)
    incomplete: bool = False      # the record used is missing details the admin still has to add
    sources: list[dict] = field(default_factory=list)
    understood_as: str | None = None    # the question after typos / slang were repaired (None = nothing repaired)
    suggestions: list[str] = field(default_factory=list)   # follow-up questions shown as buttons
    topic_hint: str | None = None   # the policy topic in the student's words ("haircut"): what a follow-up is about
    language: str = "en"            # "fil" when the chatbot's own sentences were written in Filipino

    def as_dict(self) -> dict:
        return {"answer": self.text, "kind": self.kind, "found": self.found, "confidence": self.confidence,
                "understood_as": self.understood_as, "suggestions": self.suggestions,
                "intent": {"name": self.intent, "confidence": self.intent_confidence},
                "pgpc_related": self.pgpc_related, "incomplete": self.incomplete, "sources": self.sources}


# --------------------------------------------------------------------------- small helpers
def _words(question: str) -> set[str]:
    return set(normalize_text(question).split())


def floor_label(floor) -> str:
    """'2' -> 'Floor 2'; '1st floor' and '2nd floor' are already words and stay as written."""
    f = str(floor).strip()
    return f"Floor {f}" if f.isdigit() else f


def room_label(number, name=None) -> str:
    """'204' -> 'Room 204'; 'LR 3' + 'Lecture Room 3' -> 'Lecture Room 3 (LR 3)'; 'Dark Room' stays 'Dark Room'."""
    number, name = str(number or "").strip(), str(name or "").strip()
    if number and re.fullmatch(r"\d+[A-Za-z]?", number):
        return f"Room {number}" + (f" ({name})" if name else "")
    if name and number and name.lower() != number.lower():
        return f"{name} ({number})"
    return name or number


def _join_location(building=None, floor=None, room=None, extra=None) -> str:
    """The order students are told: floor, name of the building, name of the room."""
    parts = []
    if floor:
        parts.append(floor_label(floor))
    if building:
        parts.append(f"{building}" if "building" in str(building).lower() else f"{building} building")
    if room:
        parts.append(f"Room {room}" if re.fullmatch(r"\d+[A-Za-z]?", str(room).strip()) else str(room))
    if extra:
        parts.append(str(extra))
    return ", ".join(parts)


_LIST_START = re.compile(r"^(\d+(\.\d+)*[.)]?\s|\(?[a-zA-Z0-9]{1,2}\)\s|[-•.]\s)")
_NOISE_LINE = re.compile(r"^([-_=\u2013\u2014*\s]{3,}|page\s*\d+\s*)$", re.IGNORECASE)   # "-----", "page 7" from the PDF


def tidy_text(text: str) -> str:
    """Handbook text comes from a PDF, where every line is wrapped. Join wrapped lines back into sentences,
    but keep numbered and bulleted items on their own lines."""
    lines = [l.strip() for l in (text or "").splitlines()]
    lines = [l for l in lines if not _NOISE_LINE.match(l)]
    out: list[str] = []
    blank_before = False
    for line in lines:
        if not line:
            blank_before = True
            continue
        if out and not blank_before and not _LIST_START.match(line):
            out[-1] += " " + line
        else:
            out.append(line)
        blank_before = False
    return "\n".join(out)


def excerpt(text: str, limit: int = MAX_EXCERPT_CHARS) -> tuple[str, bool]:
    """Shortens long text at a sentence or line end. Returns (text, was_cut)."""
    text = tidy_text(text)
    if len(text) <= limit:
        return text, False
    window = text[:limit]
    cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "))
    if cut < limit * 0.5:
        cut = window.rfind(" ")
    return window[: cut + 1].rstrip() + " ...", True


def _source_dict(h: Hit) -> dict:
    return {"type": h.source_type, "id": h.source_id, "title": h.title, "source": h.source}


# --------------------------------------------------------------------------- one writer per record type
# Each writer returns (text, mentioned_missing). `mentioned_missing` tells the caller that the text already
# said which details are not on file, so the generic "some details are missing" note is not repeated.
def _write_office(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    f, name = h.fields, h.title
    loc = _join_location(f.get("building"), f.get("floor"), f.get("room_number"))
    contact = ". ".join(p for p in (f"Contact number: {f['contact_number']}" if f.get("contact_number") else "",
                                    f"Email: {f['email']}" if f.get("email") else "") if p)
    about = f.get("about")
    want_loc = intent == "office_location" or bool(q & WANT_LOCATION)
    want_contact = intent == "contact_info" or bool(q & WANT_CONTACT)
    # Decided by the question's own words (the intent can say "office_location" for any question about an office).
    want_hours = bool(q & WANT_HOURS) and not (q & WANT_LOCATION) and not (q & WANT_CONTACT)
    lines, missing = [], False
    loc_line = f"The {name} is located at: {loc}." if loc else ""
    if want_hours:
        # Offices have no opening-hours field yet, so say so instead of answering a different question.
        lines.append(f"I don't have the office hours of the {name} yet.")
        missing = True
        if loc_line:
            lines.append(loc_line)
    elif want_contact and not want_loc:
        if contact:
            lines.append(f"Contact details for the {name}: {contact}.")
        else:
            lines.append(f"I don't have contact details for the {name} yet.")
            missing = True
        if loc_line:
            lines.append(loc_line)
    else:
        if loc_line:
            lines.append(loc_line)
        elif want_loc or not about:
            lines.append(f"I don't have the exact location of the {name} yet.")
            missing = True
        if contact:
            lines.append(contact + ".")
        elif want_contact:
            lines.append(f"I don't have contact details for the {name} yet.")
            missing = True
    if about and (missing or not (want_loc or want_contact)):
        lines.append(about if about.endswith((".", ")")) else about + ".")
    if loc_line and want_loc and f.get("shares"):
        lines.append(f["shares"])                                   # from the floor plan: who sits in the same room
    if loc_line and want_loc and not want_contact and not want_hours:
        missing = True        # the location was answered, so no "details missing" note for the other fields
    return " ".join(l for l in lines if l), missing


def _write_facility(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    f, name = h.fields, h.title
    loc = ", ".join(p for p in (f.get("building"), f.get("location")) if p)
    hours, equip, about = f.get("operating_hours"), f.get("equipment"), f.get("about")
    want_loc = intent == "room_location" or bool(q & WANT_LOCATION)
    want_hours = bool(q & WANT_HOURS)
    lines, missing = [], False
    if want_hours and not want_loc:
        if hours:
            lines.append(f"The {name} is open {hours}.")
        else:
            lines.append(f"I don't have the opening hours of the {name} yet.")
            missing = True
        if loc:
            lines.append(f"Location: {loc}.")
    elif want_loc:
        if loc:
            lines.append(f"The {name} is located at {loc}.")
        else:
            lines.append(f"I don't have the exact location of the {name} yet.")
            missing = True
        if hours:
            lines.append(f"Hours: {hours}.")
    else:
        lines.append(f"{name}:")
        if hours:
            lines.append(f"Hours: {hours}.")
        if loc:
            lines.append(f"Location: {loc}.")
        if equip:
            lines.append(f"Available equipment: {equip}.")
    if about and (missing or not (want_loc or want_hours)):
        lines.append(about if about.endswith((".", ")")) else about + ".")
    return " ".join(lines), missing


def _write_room(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    f = h.fields
    label = room_label(f["room_number"], f.get("room_name"))
    where = _join_location(f.get("building"), f.get("floor"))
    lines, missing = [], False
    if f.get("building") and f.get("floor"):
        lines.append(f"{label} is located at: {where}.")
    elif where:
        lines.append(f"{label} is located at: {where}. The " + ("floor" if f.get("building") else "building") + " has not been added yet.")
        missing = True
    else:
        lines.append(f"I have a record of {label}, but its building and floor have not been added yet.")
        missing = True
    if f.get("room_type"):
        lines.append(f"Type: {f['room_type']}.")
    if f.get("facility"):
        lines.append(f"Facility: {f['facility']}.")
    return " ".join(lines), missing


def _write_employee(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    f, name = h.fields, h.title
    details = [("Group / position", f.get("position")), ("Office", f.get("office")),
               ("Roster note", f.get("note")), ("Email", f.get("email")), ("Contact number", f.get("contact_number"))]
    have = [(k, v) for k, v in details if v]
    if not have:
        return (f"{name} is listed in the PGPC employee records, but their position, office and contact "
                f"details have not been added yet."), True
    lead = ""
    wants_email = bool(q & {"email", "mail", "emails"})
    wants_number = bool(q & {"number", "phone", "telephone", "call", "mobile", "cellphone"})
    wants_contact = bool(q & {"contact", "reach"}) or wants_email or wants_number
    if wants_contact:
        if wants_email and not wants_number and not f.get("email"):
            lead = f"I don't have an email address for {name} on file yet."
        elif wants_number and not wants_email and not f.get("contact_number"):
            lead = f"I don't have a contact number for {name} on file yet."
        elif not f.get("email") and not f.get("contact_number"):
            lead = f"I don't have the email or contact number of {name} on file yet."
        if lead:
            lead += " Please check with the concerned PGPC office.\n\nHere is what I do have:"
    lines = [lead or f"Here is what I have on {name}:"] + [f"- {k}: {v}" for k, v in have]
    missing = not (f.get("position") and f.get("office"))
    if missing:
        lines.append("Some details (position or office) have not been added yet.")
    return "\n".join(lines), missing


def _write_position(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    desc = h.fields.get("description")
    return (f"{h.title}: {desc}" if desc else f"{h.title} is a position in the PGPC records."), False


def _write_library(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    f = h.fields
    text = f'The library has "{h.title}"' + (f" by {f['author']}" if f.get("author") else "") + "."
    text += f" Availability: {f['availability']}." if f.get("availability") else " Its availability has not been recorded."
    if f.get("location"):
        text += f" Location: {f['location']}."
    return text, False


PROCEDURE_WORDS = {"procedure", "procedures", "process", "steps", "step", "requirements", "requirement", "paano"}
NOT_PROCEDURE = {"many", "much", "long", "often", "old", "far", "big"}


def is_procedure_question(q: set[str]) -> bool:
    """"how do I enroll" wants every step; "how many books" does not."""
    return bool(q & PROCEDURE_WORDS) or ("how" in q and not (q & NOT_PROCEDURE))


def _focused_body(content: str, q: set[str]) -> str | None:
    """The sentence(s) of a long passage that answer the question, or None to show the passage as it is."""
    from app.services.focus import focus
    from app.services.synonyms import SYNONYMS
    from app.services.text_mining import get_text_miner
    miner = get_text_miner()
    try:
        found = focus(tidy_text(content), " ".join(sorted(q)), lambda t: miner.process(t).lemmas, SYNONYMS,
                      whole_list=is_procedure_question(q))
    except Exception:          # focusing is a bonus; never let it break an answer
        return None
    if not found:
        return None
    body, _ = excerpt(found[0])
    return body


def friendly_label(h: Hit) -> str:
    """'Section 1 - Offenses, Violation and Sanctions (part 5)' -> 'Section 1 - Offenses, Violation and Sanctions
    (Chapter XIII)'. A student does not need to know how the handbook was cut into parts."""
    label = re.sub(r"\s*\(part \d+\)\s*$", "", h.fields.get("heading") or h.title or "").strip()
    chapter = (h.fields.get("category") or "").split(":")[0].strip()
    return f"{label} ({chapter})" if label and chapter.lower().startswith("chapter") else (label or h.title)


def _write_text_record(h: Hit, q: set[str], intent: str) -> tuple[str, bool]:
    """Handbook passages, uploaded-document chunks, history and FAQs: show the stored text itself."""
    label = friendly_label(h) if h.source_type == "handbook" else (h.fields.get("heading") or h.title)
    wants_all = h.source_type in ("handbook", "document") and asked_for_everything(q)
    if h.source_type in ("handbook", "document") and not wants_all:
        focused = _focused_body(h.content, q)
        if focused:
            return f'According to "{label}":\n{focused}\n(This is the part that best matches your question. ' \
                   f'Check the full document for the rest.)', False
    body, cut = excerpt(h.content, MAX_DETAIL_CHARS if wants_all else MAX_EXCERPT_CHARS)
    if h.source_type == "faq":
        return body, False
    if h.source_type == "history":
        year = h.fields.get("year")
        return f"{h.title}{f' ({year})' if year else ''}:\n{body}", False
    text = f'Here is what I found under "{label}":\n{body}'
    if cut:
        text += "\n(This is only part of the text. Ask about a more specific topic, or check the full document.)"
    return text, False


WRITERS = {"office": _write_office, "facility": _write_facility, "room": _write_room, "employee": _write_employee,
           "position": _write_position, "library": _write_library, "handbook": _write_text_record,
           "document": _write_text_record, "history": _write_text_record, "faq": _write_text_record}


def _brief(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _short_detail(h: Hit) -> str:
    """One-line summary of a record, used when several records match."""
    f = h.fields
    if h.source_type == "employee":
        return ", ".join(p for p in (f.get("position"), f.get("office")) if p) or "details not added yet"
    if h.source_type == "office":
        return (_join_location(f.get("building"), f.get("floor"), f.get("room_number"))
                or _brief(f.get("about")) or "location not added yet")
    if h.source_type == "facility":
        return (", ".join(p for p in (f.get("building"), f.get("location"), f.get("operating_hours")) if p)
                or _brief(f.get("about")) or "location not added yet")
    if h.source_type == "room":
        return _join_location(f.get("building"), f.get("floor")) or "building not added yet"
    if h.source_type == "library":
        return ", ".join(p for p in (f.get("author"), f.get("availability")) if p) or "no details recorded"
    return ""


SUGGEST_TYPES = {"handbook": "student handbook", "document": "uploaded document", "faq": "FAQ", "history": "school history",
                 "office": "office", "facility": "facility"}
SUGGEST_MIN_SCORE = 0.12
SUGGEST_MIN_COVERAGE = 0.5      # a suggestion must contain at least half of the question's (weighted) words
MAX_SUGGESTIONS = 3
SUGGEST_LEAD = ("I couldn't find an exact answer to that, but these are the closest topics I have. "
                "Try asking about one of them:")


def suggestions(result: RetrievalResult) -> list[str]:
    """Closest topics for a question that found no answer, so the student is never left at a dead end."""
    out, seen = [], set()
    for h in result.hits:
        if h.source_type not in SUGGEST_TYPES or h.score < SUGGEST_MIN_SCORE or h.coverage < SUGGEST_MIN_COVERAGE:
            continue
        title = " ".join((h.title or "").split())[:100]
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append(f"- {title} ({SUGGEST_TYPES[h.source_type]})")
        if len(out) == MAX_SUGGESTIONS:
            break
    return out


NO_PERSON = ("I couldn't find that person or position in the PGPC employee records. It may not have been added yet, "
             "so please check with the concerned PGPC office. You can also ask me about an office, a facility or a "
             "handbook topic.")


# A question about a place / office / facility / contact that is not on file gets a direct reply with examples,
# instead of unrelated handbook sections as "closest topics".
ENTITY_NOT_FOUND = {
    "room_location": ("I don't have the location of that room or area on file yet.",
                      ["Where is the registrar's office?", "Where is the clinic?"]),
    "office_location": ("I don't have that office or its location on file yet.",
                        ["Where is the registrar's office?", "Where can I pay?"]),
    "facility_info": ("I don't have details about that facility on file yet.",
                      ["What are the clinic hours?", "What are the library rules?"]),
    "library_info": ("I don't have that library detail (for example its opening hours) on file yet.",
                     ["What are the library rules?", "How many books can I borrow?"]),
    "contact_info": ("I don't have that contact detail on file yet.",
                     ["What are the clinic hours?", "Who is the president of PGPC?"]),
}


HOURS_WORDS = {"hours", "hour", "open", "opens", "close", "closes", "closing", "opening", "time"}
TEXT_SOURCES = {"handbook", "document", "history", "faq"}
HOURS_RE = re.compile(r"\b(\d{1,2}(:\d{2})?\s*(a\.?m|p\.?m)\b|hours?\b|schedule|monday|tuesday|friday|daily|weekdays?)", re.I)


def _topic_label(question: str | None) -> str:
    """'what is the policy on fighting' -> 'fighting' (at most 3 words, else empty)."""
    if not question:
        return ""
    from app.services.policy_detail import topic_terms
    words = normalize_text(question).split()
    terms = topic_terms(words)
    return " ".join(terms) if 1 <= len(terms) <= 3 else ""


def _not_found_text(result: RetrievalResult, intent_name: str | None = None, force_entity: bool = False,
                    question: str | None = None) -> str:
    if intent_name == "employee_info":
        return NO_PERSON
    close = suggestions(result)
    if intent_name in ENTITY_NOT_FOUND and (close or force_entity):
        # the "closest topics" for a missing place/office/contact are unrelated handbook sections, so say plainly
        # that it is not on file and show what can be asked instead
        lead, examples = ENTITY_NOT_FOUND[intent_name]
        return (lead + " Please check with the concerned PGPC office.\n\nI can help with these, for example: "
                + "; ".join(f'"{e}"' for e in examples))
    if not close:
        topic = _topic_label(question)
        if topic:
            return (f'I couldn\'t find anything about "{topic}" in the PGPC Student Handbook or records. It may not be '
                    "covered, or it may use different words, so try rephrasing it or check with the concerned PGPC "
                    "office. For example: " + "; ".join(f'"{e}"' for e in EXAMPLES) + ".")
        return NOT_FOUND
    return SUGGEST_LEAD + "\n" + "\n".join(close) + "\nOr check with the concerned PGPC office."


# --------------------------------------------------------------------------- the main function
def compose_answer(question: str, intent, result: RetrievalResult) -> Answer:
    """`intent` needs `.intent` and `.confidence` (an IntentResult from Phase 6). Pure function: no database."""
    name, conf = intent.intent, float(intent.confidence)

    def done(text, kind, **kw):
        base = dict(intent=name, intent_confidence=conf, found=False, confidence="none", pgpc_related=None)
        base.update(kw)
        return Answer(text=text, kind=kind, **base)

    if not (question or "").strip():
        return done(EMPTY, "empty")
    if name in SMALL_TALK:
        return done(SMALL_TALK[name], "small_talk")
    if name == "out_of_scope":
        return done(OUT_OF_SCOPE, "out_of_scope", pgpc_related=False)

    best = result.best
    if not result.found or best is None:
        # A recognised PGPC topic with no record is still a PGPC question; an unclear one is not judged.
        return done(_not_found_text(result, name, question=question), "not_found",
                    pgpc_related=None if name == "unknown" else True)

    words = _words(question)
    if name in ENTITY_NOT_FOUND and words & HOURS_WORDS and best.source_type in TEXT_SOURCES \
            and not HOURS_RE.search(best.content or ""):
        # "What time is the library open?" must not be answered with a passage about "open shelves"
        return done(_not_found_text(result, name, force_entity=True), "not_found", pgpc_related=True)
    same_kind = [h for h in result.hits
                 if h.source_type == best.source_type and h.score >= best.score * LIST_SCORE_RATIO]

    if best.source_type in LISTABLE and len(same_kind) >= 2:
        shown = same_kind[:MAX_LIST_ITEMS]
        lines = ["I found these matching records:"]
        for h in shown:
            detail = _short_detail(h)
            lines.append(f"- {h.title}" + (f" ({detail})" if detail else ""))
        if len(same_kind) > len(shown):
            lines.append(f"...and {len(same_kind) - len(shown)} more. Ask about a specific one for details.")
        else:
            lines.append("Ask about a specific one for more details.")
        used, text, kind, incomplete = shown, "\n".join(lines), "list", any(h.incomplete for h in shown)
    else:
        text, mentioned = WRITERS.get(best.source_type, _write_text_record)(best, words, name)
        incomplete = best.incomplete
        if incomplete and not mentioned:
            text += "\n" + INCOMPLETE_NOTE
        used, kind = [best], "answer"

    # "Closest match" wording is for weak matches. When every word of the question was found in the record, a low
    # score only means the record has a long description (which dilutes TF-IDF), so no warning is needed.
    if result.confidence == "low" and best.coverage < FULL_COVERAGE and not _title_names_topic(best, result):
        text = LOW_CONFIDENCE_LEAD + "\n\n" + text
    if kind == "answer":
        text += f"\n\nSource: {best.source}"
    return done(text, kind, found=True, confidence=result.confidence, pgpc_related=True,
                incomplete=incomplete, sources=[_source_dict(h) for h in used])


_GENERIC_TITLE_WORDS = {"student", "students", "school", "college", "section", "policy", "policies", "rule", "rules",
                        "pgpc", "handbook", "chapter", "general", "about", "guidelines", "procedure", "procedures"}


def _title_names_topic(hit: Hit, result: RetrievalResult) -> bool:
    """True when a distinctive word of the question is in the record's own title ('absences' -> 'Absences and
    Tardiness'). The passage is then the right one even if a long text gave it a modest score, so no
    'I am not sure' warning is shown."""
    if hit.source_type not in TEXT_SOURCES:
        return False
    title = {w[:5] for w in normalize_text(hit.title or "").split() if len(w) >= 4 and w not in _GENERIC_TITLE_WORDS}
    keys = {k[:5] for k in (result.keywords or []) if len(k) >= 4 and k not in _GENERIC_TITLE_WORDS}
    return bool(title & keys)


def combine_answers(parts: list[tuple[str, "Answer"]]) -> "Answer":
    """One reply for a message that held several questions. Pure: no database."""
    lines = [f"You asked {len(parts)} questions. Here are the answers:"]
    for n, (q, a) in enumerate(parts, 1):
        lines.append(f"\n{n}) {q}\n{a.text}")
    found = [a for _, a in parts if a.found]
    first = parts[0][1]
    sources = [src for _, a in parts for src in a.sources]
    return Answer(text="\n".join(lines), kind="multi", intent=first.intent, intent_confidence=first.intent_confidence,
                  found=bool(found), confidence=found[0].confidence if found else "none", pgpc_related=True,
                  incomplete=any(a.incomplete for a in found), sources=sources)


OVERVIEW_EXAMPLES = ["What does the handbook say about attendance?", "What is the dress code?",
                     "How do I enroll?", "What is the library borrowing policy?"]


def overview_answer(db: Session) -> "Answer | None":
    """\"What are the policies in PGPC?\" -> the chapters of the student handbook, with examples to ask next."""
    from sqlalchemy import func, select
    from app.models import HandbookSection
    rows = db.execute(select(HandbookSection.category, func.min(HandbookSection.id))
                      .where(HandbookSection.category.is_not(None)).group_by(HandbookSection.category)
                      .order_by(func.min(HandbookSection.id))).all()
    chapters = [" ".join(c.split()) for c, _ in rows if c and c.strip()][:20]
    if not chapters:
        return None
    text = ("PGPC's policies are in the Student Handbook. It covers these areas:\n"
            + "\n".join(f"- {c}" for c in chapters)
            + "\n\nAsk me about any topic, for example: " + "; ".join(f'"{e}"' for e in OVERVIEW_EXAMPLES))
    return Answer(text=text, kind="list", intent="handbook_policy", intent_confidence=1.0, found=True,
                  confidence="high", pgpc_related=True,
                  sources=[{"type": "handbook", "id": None, "title": "Student Handbook overview",
                            "source": "PGPC Student Handbook"}])


DETAIL_INTENTS = {"handbook_policy", "unknown", "faq_general", "library_info"}
PEOPLE_SKIP_INTENTS = {"greeting", "thanks", "goodbye", "bot_info"}


def people_role_answer(db: Session, question: str, intent) -> "Answer | None":
    """\"Who is the president of PGPC?\", \"who is utility staff?\", \"who are the faculty?\": answered from the
    officials named in the handbook and from the employee records. None = not a role question."""
    from app.services import people
    if intent.intent in PEOPLE_SKIP_INTENTS:
        return None
    try:
        found = people.people_answer(db, question, intent.intent)
    except Exception:                                    # a bonus feature: never let it break an answer
        logging.getLogger("pgpc.answer").exception("people answer failed")
        return None
    if found is None:
        return None
    return Answer(text=found.text, kind="answer", intent="employee_info", intent_confidence=float(intent.confidence),
                  found=found.found, confidence="high" if found.found else "none", pgpc_related=True,
                  incomplete=found.incomplete, sources=found.sources)


def detail_answer(db: Session, question: str, intent, result: RetrievalResult) -> "Answer | None":
    """An upgrade of the Phase 8 answers: a student who asks for a policy, rules, details or a penalty (or just names a topic such as
    "haircut") gets EVERYTHING the handbook says about it, put together from every place it is mentioned,
    with the offense class and sanctions. Returns None when the normal one-passage answer is the better reply."""
    from app.services import policy_detail
    from app.services.synonyms import SYNONYMS
    words = normalize_text(question).split()
    asked_detail = wants_full_detail(words)
    # The classifier may call an unfamiliar PGPC topic "out_of_scope" (e.g. cellphone rules). When the student asked
    # for a policy/details AND the handbook really has text on it, the handbook is the proof that it is a PGPC topic.
    dress = policy_detail.is_dress_question(words)         # uniform / attire / what to wear / the uniform schedule
    rescue = False                                       # the classifier is unsure, but the handbook may clearly have the topic
    if not dress and intent.intent not in DETAIL_INTENTS and not (intent.intent in {"out_of_scope", "faq_general"} and asked_detail):
        from app.services.policy_detail import NARROW_WORDS
        if intent.intent in {"out_of_scope", "facility_info", "enrollment_info", "school_history", "contact_info"} \
                and not set(words) & NARROW_WORDS:            # "where is..." / "who is..." keep their own answers
            rescue = True
        if not rescue:
            return None                                      # offices, people, rooms... are answered from their records
    best = result.best
    if best is not None and best.source_type == "faq" and result.found and result.confidence in ("high", "medium"):
        return None                                      # an FAQ the admin wrote is the official answer
    topic_only = is_topic_only(words) and (
        (result.found and best is not None and best.source_type == "handbook") or not result.found)
    if rescue and result.found and best is not None and best.source_type != "handbook" and not asked_detail:
        return None                                      # the normal answer (a record, an FAQ) is already a real one
    if not (asked_detail or topic_only or dress or rescue):
        return None
    try:
        found = policy_detail.build_detail_answer(db, words, SYNONYMS, require_titled=rescue)
    except Exception:                                    # a bonus feature: never let it break an answer
        logging.getLogger("pgpc.answer").exception("detailed answer failed")
        return None
    if found is None:
        return None
    from app.services.policy_detail import closest_label, missing_topic_words, topic_terms
    hint = " ".join(topic_terms(words)[:3]) or None
    body = found.text.split("\n", 1)[1] if found.text.startswith("Here is what") else found.text
    gaps = missing_topic_words(body, topic_terms(words), SYNONYMS)
    if gaps and not dress and not rescue:               # the passage found misses part of what was asked
        subject = " ".join(topic_terms(words))
        near = closest_label(found.sources)
        text = (f'I couldn\'t find anything specific about "{subject}" in the PGPC Student Handbook, so I would rather not '
                f'guess. ')
        if near:
            text += f'The closest topic I have is "{near}". Ask "What does the handbook say about {near.lower()}?" to read it. '
        text += "You can also check with the concerned PGPC office, such as the Office of Student Affairs (OSA)."
        return Answer(text=text, kind="answer", intent=intent.intent, intent_confidence=float(intent.confidence),
                      found=False, confidence="none", pgpc_related=True, incomplete=False, sources=[], topic_hint=hint)
    return Answer(text=found.text, kind="answer", intent=intent.intent, intent_confidence=float(intent.confidence),
                  found=True, confidence="high", pgpc_related=True, incomplete=found.incomplete, sources=found.sources,
                  topic_hint=hint)


_QUICK_LINKS_BROKEN = False


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(text or ""))


_FLOOR_WORDS = {"ground": "1st floor", "1st": "1st floor", "first": "1st floor", "1": "1st floor",
                "2nd": "2nd floor", "second": "2nd floor", "2": "2nd floor"}
_LOCATION_TRIGGERS = {"where", "find", "located", "location", "saan", "nasaan", "locate"}
_NAME_STOP = {"where", "is", "are", "the", "of", "can", "i", "find", "located", "location", "office", "room", "mr", "mrs",
              "ms", "dr", "atty", "sir", "maam", "ma", "am", "a", "an", "at", "in", "for", "to", "pgpc", "college", "does",
              "work", "works", "working", "stay", "sit", "saan", "nasaan", "si", "ni", "ang", "po", "what", "floor", "on"}


def _person_place(e) -> str:
    o = e.office
    if not o:
        return ""
    loc = _join_location(o.building, o.floor, o.room_number)
    return f"{o.name}" + (f", located at: {loc}" if loc else "")


def _employees_named(employees, words: set[str]):
    """Employees whose last name and at least one more name word are in the question ('nicky solis', 'solis nicky')."""
    from app.utils.text_cleaner import strip_accents
    out = []
    for e in employees:
        last = set(strip_accents(e.last_name or "").lower().split())
        first = set(strip_accents(e.first_name or "").lower().replace(".", "").split())
        if last and last <= words and first & words:
            out.append(e)
    return out


_HONORIFICS = {"dr", "mr", "mrs", "ms", "atty", "attorney", "engr", "sir", "maam", "madam", "prof", "doc", "ph", "d", "lpt", "mpa"}
_ASK_PREFIX = re.compile(r"^(?:who is|who s|whos|who are|sino si|sino po si|sino|tell me about|info on|information about|about|details of|details about|show me|find)\s+")


def _name_lookup(db: Session, q: str):
    """'solis', 'dr vinas', 'who is diaz': a bare person name. One match gives the person's title and office; several
    matches (two Diaz, two Abu) are listed with their titles so the student can pick."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from app.models import Employee
    from app.services import people
    from app.utils.text_cleaner import strip_accents
    body = _ASK_PREFIX.sub("", q.strip())
    tokens = [strip_accents(w).lower() for w in body.split() if strip_accents(w).lower() not in _HONORIFICS]
    if not tokens or len(tokens) > 4 or any(len(w) < 3 for w in tokens):
        return None
    employees = list(db.scalars(select(Employee).options(joinedload(Employee.position), joinedload(Employee.office))))
    def name_tokens(e):
        parts = (e.first_name, e.last_name) if len(tokens) == 1 else (e.first_name, e.middle_name, e.last_name)
        return set(strip_accents(" ".join(x for x in parts if x)).lower().replace(".", "").split())
    hits = [e for e in employees if set(tokens) <= name_tokens(e)]
    if not hits:
        return None
    if len(hits) == 1:
        e = hits[0]
        if e.position and people._real_title(e):
            return people.write_titled([e], people.RoleQuery(role=[], qualifier=[], plural=False, count=False, text="",
                                                             contact="")), True
        return None                                      # no title on file: the normal person answer says so
    lines = ["I found more than one person with that name:"]
    for e in hits[:8]:
        extra = ", ".join(x for x in (e.position.name if e.position else None, e.office.name if e.office else None) if x)
        lines.append(f"- {people._person_name(e)}" + (f" ({extra})" if extra else " (details not added yet)"))
    lines.append("Ask about one of them by full name for more details.")
    return "\n".join(lines) + "\n\nSource: PGPC employee records", True


def _campus_people_lookup(db: Session, english: str):
    """'Where is Nicky Solis / the librarian / the dean of CCBA', 'who works in the registrar office' and
    'what is on the 2nd floor', answered from the personnel list and the building plans."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from app.models import Employee, Office, Room
    from app.services import people
    q = normalize_text(english)
    words = set(q.split())
    named_card = _name_lookup(db, q)
    if named_card is not None:
        return named_card
    where = bool(words & _LOCATION_TRIGGERS) or bool(re.search(r"\bwhat floor\b", q))
    works = bool(re.search(r"\bwho (?:works?|is|are|stays?|sits?)\s+(?:in|at|inside)\b", q))
    floors = [_FLOOR_WORDS[w] for w in q.split() if w in _FLOOR_WORDS]
    on_floor = bool(re.search(r"\b(?:what|which|list|show)\b.*\b(?:on|in)\b.*\bfloor\b|\bfloor\b.*\b(?:rooms?|offices?)\b", q)) and floors
    if not (where or works or on_floor):
        return None
    employees = list(db.scalars(select(Employee).options(joinedload(Employee.position), joinedload(Employee.office))))
    # 1) what is on a floor
    if on_floor and not where:
        floor = floors[0]
        by_building: dict[str, list[str]] = {}
        for o in db.scalars(select(Office)):
            if o.floor == floor and o.building:
                by_building.setdefault(o.building, []).append(o.name)
        for r in db.scalars(select(Room)):
            if r.floor == floor and r.building and (r.room_type or "") not in {"Comfort room", "Storage"}:
                by_building.setdefault(r.building, []).append(room_label(r.room_number, r.room_name))
        if by_building:
            lines = [f"This is what I have on the {floor}:"]
            for b, items in by_building.items():
                lines.append(f"{b}:")
                lines += [f"- {i}" for i in items]
            return "\n".join(lines) + "\n\nSource: PGPC room and office records", True
        return None
    # 2) who works in an office
    if works:
        offices = list(db.scalars(select(Office)))
        qset = words - _NAME_STOP - {"who", "works", "work", "stays", "sits", "inside"}
        if "hr" in qset:
            qset |= {"human", "resources"}
        if "cashier" in qset:
            qset |= {"cashiers"}
        best = None
        for o in offices:
            ow = {w.rstrip("s") if w.endswith("'s") else w for w in normalize_text(o.name).split()
                  if w not in _NAME_STOP and w != "hr"}
            if ow and ow <= qset and (best is None or len(ow) > best[0]):
                best = (len(ow), o)
        if best:
            o = best[1]
            staff = [e for e in employees if e.office_id == o.id]
            if staff:
                lines = [f"These are the people I have in the {o.name}:"]
                lines += [f"- {people._person_name(e)}: {e.position.name if e.position else 'staff'}" for e in staff]
                return "\n".join(lines) + "\n\nSource: PGPC employee records", True
            return (f"I don't have anyone on file for the {o.name} yet.\n\nSource: PGPC employee records"), False
        return None
    # 3) where is a person / a job title
    if not where:
        return None
    named = _employees_named(employees, words)
    held = []
    if len(named) == 1:
        held = named
    elif not named:
        if words & {"office", "cashier", "accounting", "admission", "clinic", "osa", "csg", "mis"}:
            return None                                  # "where is the registrar office" is an office question
        rest = " ".join(w for w in q.split() if w not in _LOCATION_TRIGGERS and w not in {"is", "are", "can", "i", "what", "floor", "does", "work", "works"})
        pq = people.parse_role_question("who is " + rest)
        if pq is not None:
            extra = [w for w in pq.qualifier if w not in people.FILLER and w not in people.PGPC_WORDS]
            roles = pq.role + extra
            held = [e for e in people.employees_for_role(employees, roles)
                    if people._real_title(e) and people._is_head_title(e, pq.role)]
    if not held and not named:                       # "where is the guidance counselor": only an assistant is on file
        pq2 = people.parse_role_question("who is " + " ".join(w for w in q.split() if w not in _LOCATION_TRIGGERS and w not in {"is", "are", "can", "i", "what", "floor"}))
        if pq2 is not None:
            held = [e for e in people.employees_for_role(employees, pq2.role + [w for w in pq2.qualifier if w not in people.FILLER and w not in people.PGPC_WORDS])
                    if people._real_title(e)]
    if not held:
        return None
    lines = []
    for e in held[:5]:
        name = people._person_name(e)
        title = e.position.name if e.position else None
        place = _person_place(e)
        if place:
            lines.append(f"{name}" + (f" ({title})" if title else "") + f" is at the {place}.")
        else:
            lines.append(f"{name}" + (f" ({title})" if title else "") + " is on the PGPC staff list, but I don't have the office location on file yet.")
    return "\n".join(lines) + "\n\nSource: PGPC employee records", True


def _campus_lookup(db: Session, english: str):
    """Exact room (LR 3, Com Lab 2, Crime Lab 1...) and 'rooms in <building>' questions, answered from the floor plans."""
    from sqlalchemy import select
    from app.models import Room, Office
    q = normalize_text(english)
    words = set(q.split())
    if not (words & {"where", "location", "located", "find", "locate", "rooms", "room", "lab", "laboratory", "lr", "saan", "nasaan", "what", "which", "list"}):
        return None
    rooms = list(db.scalars(select(Room)))
    if not rooms:
        return None
    q = q.replace("main building", "white building").replace("building 2", "yellow building").replace("second building", "yellow building")
    words = set(q.split())
    qc = _compact(q)
    # 1) "what rooms/offices are in building 2 / main building"
    if words & {"rooms", "offices", "room", "office"} and words & {"in", "at", "inside", "sa", "list", "all"}:
        for b in sorted({r.building for r in rooms if r.building}, key=len, reverse=True):
            if _compact(b) in qc and not any(_compact(a) in qc for r in rooms for a in (r.room_number, r.room_name) if a):
                rs = [r for r in rooms if r.building == b]
                os_ = [o for o in db.scalars(select(Office)) if o.building == b]
                lines = [f"These are the rooms and offices I have in {'' if b.lower().startswith('building') else 'the '}{b}:"]
                for o in os_:
                    lines.append(f"- {o.name}" + (f" ({floor_label(o.floor)})" if o.floor else ""))
                for r in rs:
                    lines.append(f"- {room_label(r.room_number, r.room_name)}" + (f" ({floor_label(r.floor)})" if r.floor else ""))
                return "\n".join(lines) + "\n\nSource: PGPC room and office records", True
    # 1b) "where is the comfort room / CR / restroom": there are several, so list them all with their floors
    if words & {"cr", "comfort", "restroom", "toilet", "bathroom", "banyo"} and not (words & {"male", "female", "pwd", "men", "women"}):
        crs = [r for r in rooms if (r.room_type or "").lower() == "comfort room"]
        if crs:
            lines = ["There is more than one comfort room (CR) on campus:"]
            for r in crs:
                lines.append(f"- {r.room_name or r.room_number}: {_join_location(r.building, r.floor)}")
            return "\n".join(lines) + "\n\nSource: PGPC room records", True
    # 2) one specific room: its number/name appears in the question (word-boundary aware)
    def canon(t: str) -> str:
        t = " " + normalize_text(t or "") + " "
        for old, new_ in ((" lecture room ", " lr "), (" computer laboratory ", " com lab "), (" computer lab ", " com lab "),
                          (" crime laboratory ", " crime lab "), (" criminology lab ", " crime lab "), (" room ", " lr ")):
            t = t.replace(old, new_)
        return t
    qn = canon(q)
    best, best_len = [], 0
    for r in rooms:
        for a_ in (r.room_number, r.room_name):
            c = canon(a_).strip()
            if len(c.replace(" ", "")) < 3 or f" {c} " not in qn:
                continue
            if len(c) > best_len:
                best, best_len = [r], len(c)
            elif len(c) == best_len and r not in best:
                best.append(r)
    if len(best) == 1:
        r = best[0]
        f = {"room_number": r.room_number, "room_name": r.room_name, "building": r.building, "floor": r.floor,
             "room_type": r.room_type, "facility": r.facility.name if r.facility else None}
        text, missing = _write_room(Hit(source_type="room", title="", fields=f, score=1.0) if False else type("H", (), {"fields": f})(), set(), "")
        return text + "\n\nSource: PGPC room records", not missing
    return None


def _school_facts(db: Session, english: str):
    """(text, found) for 'how did PGPC begin' and 'where is PGPC located', or None."""
    from app.services import identity
    words = normalize_text(english).split()
    try:
        if identity.is_location_question(words):
            return identity.LOCATION_TEXT, True
        if identity.is_history_question(words):
            text = identity.history_answer(db)
            return (text, True) if text else None
    except Exception:
        logging.getLogger("pgpc.answer").exception("school facts failed")
    return None


def _vision_mission(db: Session, english: str):
    from app.services import identity
    try:
        return identity.vision_mission_answer(db, normalize_text(english).split())
    except Exception:                                    # a bonus feature: never let it break an answer
        logging.getLogger("pgpc.answer").exception("vision/mission answer failed")
        return None


def _admin_link(db: Session, question: str, intent):
    """A link the admin added in the dashboard (Quick links) whose keywords are in the question."""
    global _QUICK_LINKS_BROKEN
    from app.services import quick_links
    if intent.intent in PEOPLE_SKIP_INTENTS or _QUICK_LINKS_BROKEN:
        return None
    try:
        return quick_links.find_link(db, question)
    except Exception:                                    # e.g. the table does not exist yet
        db.rollback()
        _QUICK_LINKS_BROKEN = True                       # say it once, then stop asking
        logging.getLogger("pgpc.answer").warning("quick links are off: restart the server (it updates the database)")
        return None


def _answer_one(db: Session, question: str, classifier, top_k: int) -> "Answer":
    from app.services.input_reader import get_vocabulary, read_input
    from app.services.query_rewrite import is_overview
    try:
        read = read_input(question, get_vocabulary(db))   # typos, texting slang and Taglish -> clean English
    except Exception:                                    # the reader is a bonus: never let it break an answer
        logging.getLogger("pgpc.answer").exception("input reader failed")
        read = None
    english = read.text if read else question
    if is_overview(english):
        overview = overview_answer(db)
        if overview is not None:
            return overview
    intent = classifier.predict(english)
    from app.services import quick_links
    enroll_url = (get_settings().enrollment_url or "").strip()
    enroll_mode = quick_links.enrollment_mode(english) if enroll_url and intent.intent not in PEOPLE_SKIP_INTENTS else None
    if enroll_mode == "how":
        answer = Answer(text=quick_links.enrollment_link_answer(enroll_url), kind="answer", intent="enrollment_info",
                        intent_confidence=float(intent.confidence), found=True, confidence="high", pgpc_related=True,
                        sources=[{"type": "link", "id": None, "title": "PGPC online enrollment",
                                  "source": "PGPC online enrollment"}])
    elif (link := _admin_link(db, english, intent)) is not None:
        answer = Answer(text=quick_links.link_answer_text(link), kind="answer", intent=intent.intent,
                        intent_confidence=float(intent.confidence), found=True, confidence="high", pgpc_related=True,
                        sources=[{"type": "link", "id": link.id, "title": link.title, "source": "PGPC quick links"}])
    elif (vm := _vision_mission(db, english)) is not None:
        answer = Answer(text=vm, kind="answer", intent="faq_general", intent_confidence=float(intent.confidence),
                        found=True, confidence="high", pgpc_related=True,
                        sources=[{"type": "handbook", "id": None, "title": "Vision and Mission (Chapter I)",
                                  "source": "PGPC Student Handbook"}])
    elif (campus := (_campus_people_lookup(db, english) or _campus_lookup(db, english))) is not None:
        answer = Answer(text=campus[0], kind="answer", intent="room_info" if False else intent.intent,
                        intent_confidence=float(intent.confidence), found=campus[1], confidence="high", pgpc_related=True,
                        sources=[{"type": "room", "id": None, "title": "PGPC room records", "source": "PGPC room records"}])
    elif (facts := _school_facts(db, english)) is not None:
        answer = Answer(text=facts[0], kind="answer", intent="school_history", intent_confidence=float(intent.confidence),
                        found=facts[1], confidence="high" if facts[1] else "none", pgpc_related=True,
                        sources=[{"type": "handbook", "id": None, "title": "Chapter I", "source": "PGPC Student Handbook"}]
                        if facts[1] else [])
    else:
        answer = people_role_answer(db, english, intent)
        if answer is None:
            result = retrieve(db, english, intent.intent if intent.intent != "unknown" else None, top_k=top_k)
            detailed = detail_answer(db, english, intent, result)
            answer = detailed if detailed is not None else compose_answer(english, intent, result)
            from app.services import identity
            best = result.best
            admin_faq = best is not None and best.source_type == "faq" and result.found
            if identity.is_headcount_question(normalize_text(english).split()) and not admin_faq:
                answer = Answer(text=identity.HEADCOUNT_TEXT, kind="answer", intent=intent.intent,
                                intent_confidence=float(intent.confidence), found=False, confidence="none",
                                pgpc_related=True)
            if enroll_mode == "requirements" and answer.found:
                answer.text = quick_links.add_link_to_answer(answer.text, enroll_url)
    if read is not None and read.reply_in_filipino:
        from app.services.filipino_reply import localize
        answer.text = localize(answer.text)             # the chatbot's own sentences in Filipino; handbook text untouched
        answer.language = "fil"
    if read is not None and read.display:
        answer.understood_as = read.display             # "Understood as: what is the haircut policy"
    from app.services.suggestions import suggest_followups
    answer.suggestions = suggest_followups(english, answer.kind, answer.found, question)
    return answer


def generate_answer(db: Session, question: str, top_k: int = 5) -> Answer:
    """Full pipeline for one message (stateless; chat sessions are in chat_service). A message with several
    questions is answered question by question."""
    from app.services.intent_classifier import get_intent_classifier   # imported late: loads the model on first use
    from app.services.query_rewrite import split_questions
    question = clean_user_input(question)[: get_settings().max_question_chars]
    classifier = get_intent_classifier()
    subs = []
    for sq in split_questions(question):               # the same question typed again and again is answered once
        key = normalize_text(sq)
        if key and key not in {normalize_text(x) for x in subs}:
            subs.append(sq)
    subs = subs[:5] or [question]                       # and a message is answered for at most 5 different questions
    if len(subs) == 1:
        return _answer_one(db, subs[0] if len(subs) < len(split_questions(question)) else question, classifier, top_k)
    return combine_answers([(q, _answer_one(db, q, classifier, top_k)) for q in subs])


def _demo(question: str) -> None:
    from app.database.database import SessionLocal
    with SessionLocal() as db:
        a = generate_answer(db, question)
    print(f"Question   : {question}")
    print(f"Intent     : {a.intent} ({a.intent_confidence:.2f})   kind={a.kind}   confidence={a.confidence}")
    print(f"Sources    : {[s['title'] for s in a.sources]}")
    print("Answer     :")
    print("  " + a.text.replace("\n", "\n  "))


if __name__ == "__main__":
    _demo(" ".join(sys.argv[1:]) or "Where is the registrar office?")
