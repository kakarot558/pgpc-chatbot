"""Seed script:  python -m app.database.seed

Loads ONLY data that came from files the project owner supplied:
  - data/seed/PGPC_EMPLOYEES_2026.xlsx  -> employees (names only) + 2 roster categories
  - data/handbook/HANDBOOKTXT_raw.txt   -> handbook_sections
  - a handwritten enrollment note       -> one UNPUBLISHED (inactive) FAQ
  - the handbook's own chapters       -> 5 offices and 3 facilities that the handbook names
                                         (name + what the handbook says they do; NO invented locations)
Rooms, positions/titles, buildings/floors/room numbers and contact details are NOT invented; the
admin adds them in the dashboard. The script is safe to run more than once.
"""
import re
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models import FAQ, Employee, Facility, HandbookSection, Office, Position

ROOT = Path(__file__).resolve().parents[2]
EMPLOYEE_FILE = ROOT / "data" / "seed" / "PGPC_EMPLOYEES_2026.xlsx"
HANDBOOK_FILE = ROOT / "data" / "handbook" / "HANDBOOKTXT_raw.txt"
HANDBOOK_SOURCE = "PGPC Student Handbook"
PLACEHOLDER = "[ADMIN: ADD VERIFIED PGPC INFORMATION]"
MAX_SECTION_CHARS = 3000


# ----------------------------------------------------------------- helpers
SMALL_WORDS = {"and", "of", "on", "for", "the", "to", "in", "or"}


def smart_title(text: str) -> str:
    """Title-case ALL-CAPS headings but keep acronyms like (PGPC) and (OSA) intact."""
    out = []
    for i, w in enumerate(text.split()):
        if w.startswith("(") or "/" in w or "." in w[:-1]:
            out.append(w)                       # acronym, e.g. (PGPC), O.J.T., Face-to-Face
        elif w.lower() in SMALL_WORDS and i > 0:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------- employees
def parse_name(raw: str) -> dict:
    """'ABU, JOY HINANAY' -> last 'Abu', first 'Joy Hinanay'.
    Middle names cannot be separated reliably from a roster, so the whole given-name
    part goes in first_name; the admin can refine it later."""
    raw = " ".join(raw.split())
    note = None
    m = re.search(r"\(([^)]*)\)", raw)
    if m:
        note = m.group(1)
        raw = raw.replace(m.group(0), "").strip()
    if "," in raw:
        last, first = [p.strip() for p in raw.split(",", 1)]
    else:  # no comma: we cannot tell which part is the surname, so do not guess
        last, first = raw, "[ADMIN: VERIFY NAME]"
    first = first if first.startswith("[") else first.title()
    return {"last_name": last.title(), "first_name": first, "roster_note": note}


def read_roster(path: Path = EMPLOYEE_FILE) -> list[tuple[str, str]]:
    """Returns (category, raw_name). The SIZE columns (uniform sizes) are deliberately ignored."""
    ws = load_workbook(path, read_only=True).active
    people = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        for col, category in ((0, "Faculty"), (2, "Administrative Personnel")):
            if col < len(row) and row[col] and str(row[col]).strip():
                people.append((category, str(row[col]).strip()))
    return people


def seed_employees(db: Session) -> tuple[int, int]:
    positions = {}
    for name in ("Faculty", "Administrative Personnel"):
        pos = db.scalar(select(Position).where(Position.name == name))
        if not pos:
            pos = Position(
                name=name,
                description=f"Group heading used in the PGPC 2026 roster. Specific job titles: {PLACEHOLDER}",
            )
            db.add(pos)
            db.flush()
        positions[name] = pos
    added = skipped = 0
    for category, raw in read_roster():
        parts = parse_name(raw)
        exists = db.scalar(select(Employee).where(
            Employee.last_name == parts["last_name"], Employee.first_name == parts["first_name"]))
        if exists:
            skipped += 1
            continue
        desc = f"Listed under '{category}' in the PGPC 2026 employee roster. Office and contact details: {PLACEHOLDER}"
        if parts["roster_note"]:
            desc += f" Roster note: ({parts['roster_note']})."
        db.add(Employee(first_name=parts["first_name"], last_name=parts["last_name"],
                        position_id=positions[category].id, description=desc, status="roster-2026"))
        added += 1
    return added, skipped


# ----------------------------------------------------------------- handbook
PAGE_RE = re.compile(r"^\s*page\b\s*-?\s*(\d+)?\s*[-:]?\s*(.*)$", re.I)
CHAPTER_RE = re.compile(r"^\s*chapter\s+([IVXL]+)\s*$", re.I)
SECTION_RE = re.compile(r"^\s*(?:Section|Beetion)\s+([A-Z])\b[\s\-–:.]*(.*)$")          # Section A - Title
SECTION_NUM_RE = re.compile(r"^\s*(?:Section|Beetion)\s+(\d+)\s*[-–:]\s*(.+)$")          # Section 1 - Title
ARTICLE_RE = re.compile(r"^\s*article\s+([IVX]+|\d+)\s*[-–:]?\s*(.*)$", re.I)
MESSAGE_RE = re.compile(r"^\s*(message of the municipal (?:vice )?mayor)\s*$", re.I)


def parse_handbook(text: str) -> list[dict]:
    """Cuts the raw handbook text into sections using its own headings and page markers."""
    lines = text.split("\n")
    toc = next((i for i, l in enumerate(lines) if l.strip().upper() == "TABLE OF CONTENTS"), len(lines))
    back = next((i for i, l in enumerate(lines) if l.strip().upper() == "BACK COVER"), None)
    body = lines[:toc] + (["BACK COVER"] + lines[back + 1:] if back else [])
    # Source quirk: Chapter XIX has its title line but the "CHAPTER XIX" line is missing.
    fixed = []
    for l in body:
        if l.strip().upper().startswith("POLICIES AND PROCEDURES: PRACTICUM"):
            fixed.append("Chapter XIX")
        fixed.append(l)
    body = fixed

    sections, cur = [], None
    chapter_label, page = None, None

    def start(title, number, category):
        nonlocal cur
        if cur:
            sections.append(cur)
        cur = {"title": title.strip(" -–:."), "section_number": number, "category": category,
               "source_page": str(page) if page else None, "lines": []}

    i = 0
    while i < len(body):
        line = body[i]
        m = PAGE_RE.match(line)
        if m and (m.group(1) is not None or line.strip().lower().startswith("page")):
            n = int(m.group(1)) if m.group(1) else None
            page = n if n else page  # "page 0" markers belong to the unnumbered front matter
            if m.group(1) == "0":
                page = None
            rest = m.group(2).strip()
            if rest:           # text that shares a line with the marker is still handbook content
                body[i] = rest
                continue
            i += 1
            continue
        s = line.strip()
        if re.fullmatch(r"-{5,}", s):
            i += 1
            continue
        if s.upper() == "BACK COVER":
            chapter_label = None
            start("Back Cover", "Back Cover", "Back Cover")
        elif MESSAGE_RE.match(s):
            chapter_label = None
            start(smart_title(s), None, "Messages from the Municipal Officials")
        elif CHAPTER_RE.match(s):
            roman = CHAPTER_RE.match(s).group(1).upper()
            title_parts = []
            j = i + 1
            while j < len(body) and body[j].strip() and body[j].strip() == body[j].strip().upper() \
                    and not re.match(r"^\s*(page|section|article)\b", body[j], re.I):
                title_parts.append(body[j].strip())
                j += 1
            chapter_title = smart_title(" ".join(title_parts))
            chapter_label = f"Chapter {roman}: {chapter_title}" if chapter_title else f"Chapter {roman}"
            start(chapter_label, f"Chapter {roman}", chapter_label)
            i = j
            continue
        elif len(s) <= 120 and (SECTION_RE.match(s) or SECTION_NUM_RE.match(s)):
            mm = SECTION_RE.match(s) or SECTION_NUM_RE.match(s)
            sid, title = mm.group(1), mm.group(2).strip()
            start(f"Section {sid}" + (f" - {title}" if title else ""),
                  f"{chapter_label.split(':')[0] if chapter_label else 'Front matter'}, Section {sid}", chapter_label)
        elif len(s) <= 100 and ARTICLE_RE.match(s) and chapter_label:
            mm = ARTICLE_RE.match(s)
            start(f"Article {mm.group(1)}" + (f" - {mm.group(2).strip()}" if mm.group(2).strip() else ""),
                  f"{chapter_label.split(':')[0]}, Article {mm.group(1)}", chapter_label)
        elif cur is not None:
            cur["lines"].append(line.rstrip())
        i += 1
    if cur:
        sections.append(cur)

    out = []
    for sec in sections:
        content = "\n".join(sec.pop("lines")).strip()
        content = re.sub(r"\n{3,}", "\n\n", content)
        if len(content) < 20:      # heading with no body: skip rather than publish an empty section
            continue
        for n, part in enumerate(split_long(content), start=1):
            rec = dict(sec, content=part)
            if n > 1 or len(content) > MAX_SECTION_CHARS:
                rec["title"] = f"{sec['title']} (part {n})"
            out.append(rec)
    return out


def split_long(content: str) -> list[str]:
    if len(content) <= MAX_SECTION_CHARS:
        return [content]
    parts, buf = [], ""
    for para in content.split("\n\n"):
        if buf and len(buf) + len(para) > MAX_SECTION_CHARS:
            parts.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        parts.append(buf.strip())
    return parts


def seed_handbook(db: Session) -> int:
    if db.scalar(select(HandbookSection).where(HandbookSection.source_document == HANDBOOK_SOURCE).limit(1)):
        return 0  # already loaded; the admin edits sections in the dashboard from here on
    records = parse_handbook(HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace"))
    for r in records:
        db.add(HandbookSection(source_document=HANDBOOK_SOURCE, **r))
    return len(records)


# --------------------------------------------------- offices and facilities (from the handbook)
# Every description below only restates what the PGPC Student Handbook says. Where an office or facility is,
# who to call and when it is open (unless the handbook gives hours) are NOT in the handbook, so they are left
# for the admin and the placeholder keeps the chatbot honest ("that detail has not been added yet").
# "ref" says where in the handbook the description comes from. It goes into the admin-only [ADMIN: ...] note, not
# into the description itself, so it never pollutes search results or reaches a student.
OFFICES = [
    {"name": "Office of the Registrar", "ref": "Chapters on enrollment, dropping, completion and graduation",
     "description": "Students get forms here (for example the dropping form, the completion form and the leave of "
                    "absence form) and submit required documents. Students who need a copy of their evaluation sheet "
                    "pay at the Cashier's Office first, then present the official receipt here. The Registrar also "
                    "posts the list of candidates for graduation."},
    {"name": "Cashier's Office", "ref": "Chapters on fees, dropping and evaluation sheets",
     "description": "Students pay school fees here and get an official receipt, for example the dropping fee and "
                    "the fee for a copy of the evaluation sheet."},
    {"name": "Office of Student Affairs (OSA)", "ref": "Chapter XVI",
     "description": "Handles student services: Guidance and Counseling Service, College Health Services (the College "
                    "Clinic) and Food Services (monitoring of food quality, affordability and accessibility at the "
                    "canteen)."},
    {"name": "Guidance Office", "ref": "Chapter XVI, Section A",
     "description": "Provides the Guidance and Counseling Service under the Office of Student Affairs: admission, "
                    "orientation, student information, testing, placement (career orientation, job fair), follow-up, "
                    "referral and research services, plus professional counseling by a licensed guidance counselor and "
                    "peer counseling."},
    {"name": "Sports, Arts and Culture Office (SACO)", "ref": "Chapter XVIII",
     "description": "Develops the sports, cultural and artistic talents of students, and gives students venues to "
                    "develop and showcase talents in sports, performing arts, visual arts and literary arts."},
]
FACILITIES = [
    {"name": "College Clinic", "ref": "Chapter XVI, Section B", "operating_hours": "Monday-Friday, 8 AM-5 PM",
     "description": "Provides medical check-up, dental check-up, first aid treatment, minor surgery, medicines for "
                    "common ailments and medical referrals for complicated health problems. Students who were absent "
                    "for health reasons submit a medical certificate here; the College Physician validates it and signs "
                    "the excuse slip. The clinic also runs health education seminars."},
    {"name": "College Library", "ref": "Chapter XX",
     "description": "Offers readers' services (OPAC online catalog, circulation, research assistance with the librarian "
                    "on duty, current awareness, information literacy orientation and interlibrary loan) and uses an "
                    "open-shelves system."},
    {"name": "College Canteen", "ref": "Chapter XVI, Section C",
     "description": "The College monitors food quality, affordability and accessibility at the canteen, as well as "
                    "sanitation and order in the eating areas."},
]


def _note(rec: dict, missing: str) -> str:
    """The retrieval step removes "[ADMIN: ...]" completely, so this tells the admin what to do and where the text
    came from, while the chatbot never repeats it to a student."""
    return f" [ADMIN: DESCRIPTION FROM PGPC STUDENT HANDBOOK, {rec['ref'].upper()}. ADD VERIFIED {missing}]"


def seed_offices(db: Session) -> tuple[int, int]:
    added = skipped = 0
    for rec in OFFICES:
        if db.scalar(select(Office).where(func.lower(Office.name) == rec["name"].lower())):
            skipped += 1
            continue
        db.add(Office(name=rec["name"], description=rec["description"] + _note(rec, "LOCATION, CONTACT NUMBER AND OFFICE HOURS")))
        added += 1
    return added, skipped


def seed_facilities(db: Session) -> tuple[int, int]:
    added = skipped = 0
    for rec in FACILITIES:
        if db.scalar(select(Facility).where(func.lower(Facility.name) == rec["name"].lower())):
            skipped += 1
            continue
        missing = "LOCATION" if rec.get("operating_hours") else "LOCATION AND OPENING HOURS"
        db.add(Facility(name=rec["name"], description=rec["description"] + _note(rec, missing),
                        operating_hours=rec.get("operating_hours")))
        added += 1
    return added, skipped


# -------------------------------------------------- unpublished enrollment note
def seed_enrollment_note(db: Session) -> bool:
    question = "How many students are enrolled per program? (UNVERIFIED handwritten tally)"
    if db.scalar(select(FAQ).where(FAQ.question == question)):
        return False
    answer = (
        "Handwritten tally with columns labeled 1st, 2nd, 3rd (what the columns and the term represent "
        "has not been confirmed). BSCS: 120 / 95 / 191. BSCAIM: 113 / 134 / 221. BPA: 90 / 91 / 74. "
        "BSMA: 56 / 61 / 135. Total written on the note: 1381. "
        f"{PLACEHOLDER}: confirm meaning and date, then set this FAQ active."
    )
    db.add(FAQ(question=question, answer=answer, category="enrollment", keywords="enrollment BSCS BSCAIM BPA BSMA",
               source="Admin note (handwritten, unverified)", is_active=False))
    return True


def main() -> None:
    with SessionLocal() as db:
        emp_added, emp_skipped = seed_employees(db)
        hb = seed_handbook(db)
        off_added, off_skipped = seed_offices(db)
        fac_added, fac_skipped = seed_facilities(db)
        note = seed_enrollment_note(db)
        db.commit()
    print(f"Employees added: {emp_added} (already present: {emp_skipped})")
    print(f"Handbook sections added: {hb}")
    print(f"Offices added: {off_added} (already present: {off_skipped})")
    print(f"Facilities added: {fac_added} (already present: {fac_skipped})")
    print(f"Enrollment note FAQ added (inactive): {note}")


if __name__ == "__main__":
    main()
