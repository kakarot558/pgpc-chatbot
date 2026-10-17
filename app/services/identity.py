"""Two fixed-shape answers: the school's Vision and Mission, and 'how many students' questions.

* Vision / Mission: taken from the handbook's own text (Chapter I) and shown in the official wording.
* Student counts: the handbook has no enrollment numbers, so the chatbot says so plainly instead of guessing from an
  unrelated passage. An FAQ the admin writes ("How many students are in BSCS?") still wins, because FAQs are checked
  before this runs.
"""
import re

VISION_FALLBACK = ("PGPC is a premier higher learning institution producing globally competitive and excellent "
                   "professionals and leaders instrumental to community development and nation-building.")
MISSION_FALLBACK = ("As a higher learning institution, PGPC is committed to produce globally competent professionals "
                    "and leaders with industry- based knowledge, skills, and values that will enable them achieve "
                    "their professional growth and total human development.")
_VISION_RE = re.compile(r"^Vision Statement\s*$\s*(.+?)\s*^Mission Statement\s*$", re.I | re.M | re.S)
_MISSION_RE = re.compile(r"^Mission Statement\s*$\s*(.+?)\s*^(?:Core Values|Quality Policy)\s*$", re.I | re.M | re.S)


def _one_paragraph(text: str) -> str:
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1-\2", text)          # "nation-\nbuilding" -> "nation-building"
    return re.sub(r"\s+", " ", text).strip()


def wanted_parts(words: list[str]) -> tuple[bool, bool]:
    """(vision, mission) asked for. 'admission' is not 'mission': whole words only."""
    w = set(words)
    vision = bool(w & {"vision", "visions"})
    mission = bool(w & {"mission", "missions"})
    if w & {"vmgo", "vmission"}:
        vision = mission = True
    return vision, mission


def vision_mission_text(handbook_text: str, vision: bool, mission: bool) -> str:
    v = _VISION_RE.search(handbook_text or "")
    m = _MISSION_RE.search(handbook_text or "")
    vtext = _one_paragraph(v.group(1)) if v and len(v.group(1)) < 700 else VISION_FALLBACK
    mtext = _one_paragraph(m.group(1)) if m and len(m.group(1)) < 700 else MISSION_FALLBACK
    parts = []
    if vision:
        parts.append(f"The Vision of the Padre Garcia Polytechnic College (PGPC) shall be:\n\n{vtext}")
    if mission:
        parts.append(f"The Mission of Padre Garcia Polytechnic College (PGPC) shall be:\n\n{mtext}")
    return "\n\n".join(parts) + "\n\nSource: PGPC Student Handbook, Chapter I"


def vision_mission_answer(db, words: list[str]) -> str | None:
    vision, mission = wanted_parts(words)
    if not (vision or mission):
        return None
    if set(words) & {"how", "who", "where", "when"} and not (set(words) & {"what", "state", "statement", "tell", "show"}):
        return None
    from sqlalchemy import select
    from app.models import HandbookSection
    text = "\n\n".join(r.content or "" for r in db.scalars(
        select(HandbookSection).where(HandbookSection.title.like("Chapter I:%")).order_by(HandbookSection.id)))
    return vision_mission_text(text, vision, mission)


# --------------------------------------------------------------------------- headcount
_COUNT_NOUNS = {"student", "students", "enrollee", "enrollees", "enrolled", "learner", "learners", "population",
                "enrollment", "enrolment"}
_NOT_COUNT = {"allowed", "can", "maximum", "max", "minimum", "units", "unit", "subjects", "absences", "absence",
              "books", "borrow", "pay", "fee", "fees", "late", "days", "hours", "times", "credits", "load"}


def is_headcount_question(words: list[str]) -> bool:
    w = set(words)
    return {"how", "many"} <= w and bool(w & _COUNT_NOUNS) and not (w & _NOT_COUNT)


HEADCOUNT_TEXT = ("I don't have the current number of enrolled students on file, and no student counts per program have "
                  "been added yet. The only figure in the PGPC Student Handbook is from the opening year: PGPC opened in "
                  "2024 to more than nine hundred students, 80% of them Garciano residents. For the current number, please "
                  "ask the Office of the Registrar.\n\n"
                  "If you are the PGPC admin: add FAQs such as \"How many students are in BSCS?\" in the admin "
                  "dashboard (FAQs), one for each program, and the chatbot will answer them.")


# --------------------------------------------------------------------------- how the college began, and where it is
HISTORY_WORDS = {"founded", "founder", "founders", "founding", "established", "establishment", "established", "history",
                 "ordinance", "began", "begin", "started", "opened"}
_HISTORY_RE = re.compile(r"^Responding to the Call\s*$\s*(.+?)\s*^Taking the Responsibility\s*$\s*(.+?)(?:\n\s*\n)", re.I | re.M | re.S)


def is_history_question(words: list[str]) -> bool:
    w = set(words)
    return bool(w & HISTORY_WORDS) and bool(w & {"pgpc", "college", "school", "polytechnic"}) and not (w & {"office", "room"})


def history_answer(db) -> str | None:
    from sqlalchemy import select
    from app.models import HandbookSection
    text = "\n\n".join(r.content or "" for r in db.scalars(
        select(HandbookSection).where(HandbookSection.title.like("Chapter I:%")).order_by(HandbookSection.id)))
    m = _HISTORY_RE.search(text + "\n\n")
    if not m:
        return None
    one, two = _one_paragraph(m.group(1)), _one_paragraph(m.group(2))
    return ("Here is what the PGPC Student Handbook says about how the college began:\n\nHOW PGPC BEGAN (CHAPTER I)\n"
            f"{one}\n\n{two}\n\nSource: PGPC Student Handbook, Chapter I")


_PLACE_WORDS = {"located", "location", "address"}
_NOT_PGPC_PLACE = {"office", "room", "clinic", "library", "registrar", "cashier", "guidance", "gym", "canteen", "cr", "comfort"}


def is_location_question(words: list[str]) -> bool:
    w = set(words)
    return bool(w & _PLACE_WORDS) and bool(w & {"pgpc", "college", "school", "polytechnic"}) and not (w & _NOT_PGPC_PLACE)


LOCATION_TEXT = ("Padre Garcia Polytechnic College (PGPC) is in Padre Garcia, Batangas. I don't have the street address on "
                 "file yet, so please ask the concerned PGPC office for exact directions.")
