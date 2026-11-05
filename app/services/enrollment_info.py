"""Enrollment procedures, tuition fees and student counts.

Pure functions (question text + rows -> answer text) so they are easy to test; the thin DB readers are at the bottom.
Nothing here invents a number: a student count that nobody entered is answered with 'not on file'.
"""
from __future__ import annotations

import re

from app.utils.text_cleaner import normalize_text

PROGRAMS = {
    "BSCRIM": ("BS Criminology", {"bscrim", "crim", "criminology", "bscriminology", "bscrim."}),
    "BSCS": ("BS Computer Science", {"bscs", "cs", "computer", "comsci", "compsci"}),
    "BPA": ("Bachelor of Public Administration", {"bpa", "publicadministration"}),
    "BSMA": ("BS Management Accounting", {"bsma", "accounting", "managementaccounting"}),
}
YEAR_NAMES = {1: "1st year", 2: "2nd year", 3: "3rd year", 4: "4th year"}
SEM_NAMES = {1: "1st sem", 2: "2nd sem"}

PROCEDURE_SOURCE = "Procedures during Enrollment 2026 (Office of the Registrar)"
FEE_SOURCE = "PGPC fee schedule"
COUNT_SOURCE = "PGPC enrollment records"

# --------------------------------------------------------------------------- procedures (text the Registrar prepared)
NEW_QUESTION = "What is the enrollment procedure for incoming 1st year students (A.Y. 2026-2027)?"
SEM2_QUESTION = "What is the enrollment procedure for the 2nd Sem A.Y. 2026-2027?"
PROCEDURE_CATEGORY = "Enrollment procedure"

NEW_ANSWER = """Procedures for incoming 1st Year A.Y. 2026-2027:
Those who passed the PGPC-CAT will be issued a notice to proceed for enrollment.
1. Bring your Medical Clearance.
2. The VPAA will determine the admissibility of the applicant to the program chosen as well as the qualifying standard set by the College. After such interview, the VPAA signs on the Program Qualifier.
3. The Registrar will check all requirements upon enrollment. The Registrar will issue a plan of study and registration form to all qualifying students.
4. The Accounting Office will discuss the fees to be settled in the semester and sign the registration form.
5. The student shall pay at the Cashier's Office based on the assessed fees issued by the Accounting Office. The Registration Forms shall be stamped "PAID".
6. The student shall proceed to the College Dean for Academic Policies. The College Dean will sign the Registration Form.
7. Proceed to the Guidance Counselor and fill out the profiling of students.
8. The student will proceed to the designated room for uniform fitting.
9. Pictorial for the school I.D.
10. The Registration Form shall be signed and stamped "ENROLLED" by the Registrar's Office. The Registrar will get one copy of the Registration Form and one is for the student's copy.
11. Present your Registration Form (student copy) to your subject teacher on the first day of classes. Make sure your name is in the official class list.

Prepared by: Nicky Jane A. Solis, LPT, College Registrar"""

SEM2_ANSWER = """Procedures for 2nd Sem A.Y. 2026-2027:
1. The Registrar will issue a plan of study. Go directly to your Program Chair (PC).
2. Submit copies of your computerized class cards to your PC to be attached to your Plan of Study. The PC checks and validates the student's academic records.
3. Have your plan of study checked and signed by the Program Chair.
4. Get the list of subjects you will enroll from your PC/Dean.
5. Have your subjects enlisted by the PC/Dean or an authorized enlister.
6. Have your fees assessed by the Accounting Office and get your printed Registration Form.
7. Pay your fees. Have your Registration Form stamped "PAID". The Cashier will get one copy of the Registration Form.
8. Have your Registration Form stamped "ENROLLED". The Registrar will get one copy of the Registration Form.
9. Present your Registration Form (student copy) to your subject teacher on the first day of classes. Make sure your name is in the official class list.

Prepared by: Nicky Jane A. Solis, LPT, College Registrar"""

# --------------------------------------------------------------------------- tuition (the PGPC fee table)
# program -> (year, sem) -> (academic year, Garciano, Non-Garciano)
_TABLE = {
    (1, 1): ("2025-2026", {"BSCRIM": 8400, "BSCS": 6600, "BPA": 8400, "BSMA": 8400}),
    (1, 2): ("2025-2026", {"BSCRIM": 7800, "BSCS": 6900, "BPA": 7800, "BSMA": 7800}),
    (2, 1): ("2026-2027", {"BSCRIM": 9000, "BSCS": 6900, "BPA": 7800, "BSMA": 7800}),
    (2, 2): ("2026-2027", {"BSCRIM": 8100, "BSCS": 7200, "BPA": 7800, "BSMA": 7800}),
    (3, 1): ("2027-2028", {"BSCRIM": 9000, "BSCS": 7200, "BPA": 6300, "BSMA": 8100}),
    (3, 2): ("2027-2028", {"BSCRIM": 4500, "BSCS": 6300, "BPA": 5400, "BSMA": 7200}),
    (4, 1): ("2028-2029", {"BSCRIM": 4500, "BSCS": 3300, "BPA": 3600, "BSMA": 4500}),
    (4, 2): ("2028-2029", {"BSCRIM": 4500, "BSCS": 2700, "BPA": 1800, "BSMA": 2700}),
}
_NON_GARCIANO = {
    (1, 1): {"BSCRIM": 11200, "BSCS": 8800, "BPA": 11200, "BSMA": 11200},
    (1, 2): {"BSCRIM": 10400, "BSCS": 9200, "BPA": 10400, "BSMA": 10400},
    (2, 1): {"BSCRIM": 12000, "BSCS": 9200, "BPA": 10400, "BSMA": 10400},
    (2, 2): {"BSCRIM": 10800, "BSCS": 9600, "BPA": 10400, "BSMA": 10400},
    (3, 1): {"BSCRIM": 12000, "BSCS": 9600, "BPA": 8400, "BSMA": 10800},
    (3, 2): {"BSCRIM": 6000, "BSCS": 8400, "BPA": 7200, "BSMA": 9600},
    (4, 1): {"BSCRIM": 6000, "BSCS": 4400, "BPA": 4800, "BSMA": 6000},
    (4, 2): {"BSCRIM": 6000, "BSCS": 3600, "BPA": 2400, "BSMA": 3600},
}


def default_fee_rows() -> list[dict]:
    rows = []
    for (year, sem), (ay, garciano) in _TABLE.items():
        for program, amount in garciano.items():
            rows.append(dict(program=program, residency="Garciano", year_level=year, semester=sem,
                             academic_year=ay, amount=amount))
            rows.append(dict(program=program, residency="Non-Garciano", year_level=year, semester=sem,
                             academic_year=ay, amount=_NON_GARCIANO[(year, sem)][program]))
    return rows


# --------------------------------------------------------------------------- reading the question
def canonical_program(text: str | None) -> str | None:
    t = normalize_text(text or "").replace(" ", "")
    if not t:
        return None
    for code, (_name, words) in PROGRAMS.items():
        if t == code.lower() or t in words:
            return code
    return None


def find_program(words: list[str], text: str) -> str | None:
    wset = set(words)
    if "computer science" in text or "comp sci" in text:
        return "BSCS"
    if "public administration" in text or "public admin" in text:
        return "BPA"
    if "management accounting" in text or "managerial accounting" in text:
        return "BSMA"
    if "criminology" in wset or "crim" in wset or "bscrim" in wset:
        return "BSCRIM"
    for code, (_n, aliases) in PROGRAMS.items():
        if code.lower() in wset or (wset & aliases - {"computer", "accounting"}):
            return code
    if "accounting" in wset and not (wset & {"office"}):
        return "BSMA"
    return None


_YEAR_RES = [
    (1, r"\b(?:1st|first|1)\s*(?:year|yr)s?\b|\bfreshm[ae]n\b|\bincoming\b|\bfirst year\b"),
    (2, r"\b(?:2nd|second|2)\s*(?:year|yr)s?\b|\bsophomores?\b"),
    (3, r"\b(?:3rd|third|3)\s*(?:year|yr)s?\b|\bjuniors?\b"),
    (4, r"\b(?:4th|fourth|4)\s*(?:year|yr)s?\b|\bseniors?\b"),
]
_SEM_RES = [(1, r"\b(?:1st|first|1)\s*sem(?:ester)?\b"), (2, r"\b(?:2nd|second|2)\s*sem(?:ester)?\b")]


def find_year(text: str) -> int | None:
    for n, rx in _YEAR_RES:
        if re.search(rx, text):
            return n
    return None


def find_semester(text: str) -> int | None:
    for n, rx in _SEM_RES:
        if re.search(rx, text):
            return n
    return None


def find_residency(text: str) -> str | None:
    if re.search(r"\bnon\s*garciano\b|\bnot\s+(?:a\s+)?garciano\b|\bnon\s*resident\b|\bnot\s+(?:a\s+)?resident\b"
                 r"|\btaga\s*labas\b|\boutside\b|\b(?:hindi|di|not|non)\s+(?:taga|from|of)\s*(?:padre\s*)?garcia\b"
                 r"|\bnon\s*padre\s*garcia\b|\bibang\s+(?:bayan|lugar|town)\b|\bother\s+town\b|\bdayo\b|\bnot\s+from\s+padre\b"
                 r"|\bhindi\s+(?:ako\s+)?(?:taga|residente)\b|\bhindi\s+(?:a\s+)?garciano\b", text):
        return "Non-Garciano"
    if re.search(r"\bgarciano\b|\bresident\b|\btaga\s*padre\s*garcia\b|\bpadre garcia resident\b", text):
        return "Garciano"
    return None


_ENROLL_RE = re.compile(r"\benrol\w*\b|\bmag\s*enrol\w*\b")
_PROC_WORDS = {"procedure", "procedures", "process", "steps", "step", "flow", "guide", "proseso"}
_NOT_PROCEDURE = {"requirements", "requirement", "documents", "bring", "fee", "fees", "tuition", "deadline", "schedule",
                  "dates", "date", "when", "link", "online", "much", "magkano", "cost"}
_OTHER_PROCEDURES = {"dropping", "drop", "shifting", "shift", "graduation", "graduate", "clearance", "grades", "grading",
                    "refund", "leave", "completion", "absence", "absences", "appeal", "transfer", "scholarship", "promotion"}
_NEW_WORDS = {"incoming", "freshman", "freshmen", "new", "newly", "first", "1st", "transferee", "baguhan"}
_SEM2_WORDS = {"continuing", "returning", "old", "regular", "next", "existing", "dati", "lumang"}


def procedure_kind(question: str) -> str | None:
    """'new' (incoming 1st year), 'sem2' (continuing students), 'general' (enrollment steps with no group named) or None."""
    text = normalize_text(question)
    words = set(text.split())
    if words & _NOT_PROCEDURE:
        return None
    if not _ENROLL_RE.search(text):
        # "what is the procedure for incoming 1st year" has no 'enroll' in it, but it can only mean enrollment
        qualified = bool(words & {"incoming", "freshman", "freshmen", "transferee"}) or find_year(text) == 1 \
            or find_semester(text) is not None or bool(words & _SEM2_WORDS)
        if not (words & _PROC_WORDS and qualified and not words & _OTHER_PROCEDURES):
            return None
    sem = find_semester(text)
    wants_steps = bool(words & _PROC_WORDS) or "how" in words
    new = bool(words & _NEW_WORDS) or find_year(text) == 1
    sem2 = bool(words & _SEM2_WORDS) or sem == 2 or bool(re.search(r"\b2nd sem|second sem", text))
    if not wants_steps and not (new or sem2):
        return None
    if sem2 and not (words & {"incoming", "freshman", "freshmen", "new"}):
        return "sem2"
    if new:
        return "new"
    if words & _PROC_WORDS:
        return "general"
    return None


_COUNT_BLOCK = {"employees", "employee", "faculty", "teachers", "teacher", "staff", "professors", "instructors", "deans",
                "guards", "personnel", "rooms", "room", "offices", "floors", "floor", "books", "subjects", "subject",
                "courses", "course", "programs", "units", "unit", "days", "hours", "absences", "credits", "pages",
                "units", "allowed", "can", "fees", "fee", "pay", "much"}


def is_count_question(question: str) -> bool:
    text = normalize_text(question)
    words = set(text.split())
    if words & _COUNT_BLOCK - {"courses", "course", "programs"}:
        return False
    asks = "how many" in text or "number of" in text or "total" in words or "population" in words or "bilang" in words
    if not asks:
        return False
    about = bool(words & {"student", "students", "enrolled", "enrollees", "enrollee", "learners", "population",
                          "freshmen", "freshman", "estudyante", "mag aaral"})
    return about or find_year(text) is not None or find_program(text.split(), text) is not None


def is_fee_question(question: str) -> bool:
    text = normalize_text(question)
    words = set(text.split())
    if _ENROLL_RE.search(text) and words & {"requirements", "requirement", "documents", "bring"}:
        return False
    program, year = find_program(text.split(), text), find_year(text)
    if words & {"tuition", "matrikula"}:
        return True
    if words & {"cheapest", "lowest", "least", "mura", "pinakamura", "expensive", "highest", "mahal", "pinakamahal"} and words & {"course", "program", "programs", "kurso", "courses", "tuition", "fee", "fees"}:
        return True
    if words & {"fee", "fees"} and words & {"courses", "programs", "course", "program", "kurso"} and not (words & {"dropping", "late", "penalty", "library", "id"}):
        return True
    if "garciano" in text and words & {"what", "ano", "difference", "different", "meaning", "mean", "pagkakaiba", "fee", "fees", "much", "magkano", "pay", "bayad"}:
        return True
    if words & {"fee", "fees", "cost", "price", "payment"} or "how much" in text:
        return bool(program or year) and not (words & {"dropping", "evaluation", "late", "id", "penalty", "fine", "library"})
    return False


# --------------------------------------------------------------------------- answers
def peso(n: int) -> str:
    return f"₱{n:,}"


def procedure_text(kind: str, new_text: str | None = None, sem2_text: str | None = None, link: str | None = None) -> str:
    new_text, sem2_text = new_text or NEW_ANSWER, sem2_text or SEM2_ANSWER
    body = sem2_text if kind == "sem2" else new_text
    tail = ""
    if kind == "sem2":
        tail = "\n\nAre you an incoming 1st year? Ask me: \"What is the enrollment procedure for incoming 1st year?\""
    else:
        tail = ("\n\nAre you a continuing student? Ask me: \"What is the enrollment procedure for 2nd sem?\"")
    if link:
        tail += f"\n\nTo enroll online, use the official PGPC enrollment link:\n{link}"
    tail += "\n\nYou can also ask where an office is, for example: \"Where is the cashier?\""
    return f"{body}{tail}\n\nSource: {PROCEDURE_SOURCE}"


def _label(program: str) -> str:
    return f"{program} ({PROGRAMS[program][0]})"


def words_in(text: str) -> set:
    return set(text.split())


def fee_text(rows: list[dict], question: str) -> tuple[str, bool]:
    """(text, found). rows: dicts with program, residency, year_level, semester, academic_year, amount."""
    text = normalize_text(question)
    program, year, sem, res = find_program(text.split(), text), find_year(text), find_semester(text), find_residency(text)
    if not rows:
        return ("I don't have the tuition fee table on file yet. Please ask the Accounting Office."
                f"\n\nSource: {FEE_SOURCE}"), False
    if re.search(r"\b(difference|different|meaning|pagkakaiba|ibig sabihin)\b", text) or re.fullmatch(
            r"(?:what is|what s|ano ang|ano|who is|what does)\s*(?:a\s+|an\s+|the\s+)?(?:non\s*)?garciano(?:\s+mean)?", text.strip()):
        if "garciano" in text:
            return ("Garciano means a resident of Padre Garcia; Non-Garciano means a student who is not a resident of Padre Garcia. "
                    "Non-Garciano students pay a higher tuition: the Non-Garciano fee is the Garciano fee plus one third "
                    "(for example, BSCS 1st year 1st sem is \u20b16,600 for Garciano and \u20b18,800 for Non-Garciano)."
                    f"\n\nSource: {FEE_SOURCE}"), True
    ays = re.findall(r"\b(20\d\d)\s*(?:-|to)?\s*(20\d\d)\b", text)
    ays = [f"{a}-{b}" for a, b in ays] or re.findall(r"\b(20\d\d)\b", text)
    allw = bool(words_in(text) & {"all", "lahat", "every", "each", "courses", "programs", "kurso"})
    rank = re.search(r"\b(cheap\w*|lowest|least|mura\w*|pinakamura|expensive|highest|most|mahal|pinakamahal)\b", text)
    if rank and program is None and (words_in(text) & {"course", "program", "programs", "kurso", "tuition", "fee", "fees", "bayad"}):
        low = bool(re.search(r"cheap|lowest|least|mura", text))
        pool = [r for r in rows if (res or "Garciano") == r["residency"] and (year is None or r["year_level"] == year)
                and (sem is None or r["semester"] == sem)]
        if pool:
            best = (min if low else max)(pool, key=lambda r: r["amount"])
            return (f"The {'lowest' if low else 'highest'} fee in the table{f' for {YEAR_NAMES[year]}' if year else ''} is "
                    f"{peso(best['amount'])} per semester for {_label(best['program'])}, {YEAR_NAMES[best['year_level']]}, "
                    f"{SEM_NAMES[best['semester']]} ({best['residency']}, A.Y. {best['academic_year']})."
                    f"\n\nSource: {FEE_SOURCE}"), True
    if program is None and (year or sem or res or ays or allw):
        pool = [r for r in rows if (year is None or r["year_level"] == year) and (sem is None or r["semester"] == sem)
                and (not ays or any(a in (r.get("academic_year") or "") for a in ays))]
        if pool:
            lines = [f"Fees per semester{f' for {YEAR_NAMES[year]}' if year else ''}{f', {SEM_NAMES[sem]}' if sem else ''}"
                     f"{f' ({res})' if res else ''}:"]
            keyed: dict = {}
            for r in pool:
                keyed.setdefault((r["year_level"], r["semester"], r.get("academic_year")), {}).setdefault(r["program"], {})[r["residency"]] = r["amount"]
            for (y, s, ay), progs in sorted(keyed.items(), key=lambda kv: kv[0][:2]):
                lines.append(f"{YEAR_NAMES[y]}, {SEM_NAMES[s]}" + (f" (A.Y. {ay})" if ay else "") + ":")
                for pr in PROGRAMS:
                    if pr in progs:
                        vals = [f"{n} {peso(progs[pr][n])}" for n in ("Garciano", "Non-Garciano") if n in progs[pr] and (not res or n == res)]
                        lines.append(f"- {pr}: " + " | ".join(vals))
            lines.append("Garciano = resident of Padre Garcia; Non-Garciano = not a resident.")
            return "\n".join(lines) + f"\n\nSource: {FEE_SOURCE}", True
    if program is None:
        lines = ["Tuition depends on your program, year level and semester, and on whether you are a Garciano or a "
                 "Non-Garciano. Which program do you mean? The programs on file are:"]
        lines += [f"- {_label(p)}" for p in PROGRAMS]
        lines.append('For example, ask: "How much is the tuition for BSCS 1st year 1st sem?"')
        return "\n".join(lines) + f"\n\nSource: {FEE_SOURCE}", True
    sel = [r for r in rows if r["program"] == program and (year is None or r["year_level"] == year)
           and (sem is None or r["semester"] == sem)
           and (not ays or any(a in (r.get("academic_year") or "") for a in ays))]
    if not sel:
        return (f"I don't have a fee for that combination of {program}, year level and semester."
                f"\n\nSource: {FEE_SOURCE}"), False
    cells: dict[tuple, dict] = {}
    for r in sel:
        cells.setdefault((r["year_level"], r["semester"], r.get("academic_year")), {})[r["residency"]] = r["amount"]
    head = f"Fee for {_label(program)}"
    head += f", {YEAR_NAMES[year]}" if year else ""
    head += f", {SEM_NAMES[sem]}" if sem else ""
    lines = [head + (f" ({res})" if res else "") + " (amount per semester):"]
    for (y, s, ay), vals in sorted(cells.items(), key=lambda kv: kv[0][:2]):
        parts = []
        for r_name in ("Garciano", "Non-Garciano"):
            if res and r_name != res:
                continue
            if r_name in vals:
                parts.append(f"{r_name} {peso(vals[r_name])}")
        label = f"{YEAR_NAMES[y]}, {SEM_NAMES[s]}" + (f" (A.Y. {ay})" if ay else "")
        lines.append(f"- {label}: " + " | ".join(parts))
    notes = ["Garciano = resident of Padre Garcia; Non-Garciano = not a resident."]
    if any(k[0] == 1 for k in cells):
        notes.append("The fee table lists 1st year under A.Y. 2025-2026; please confirm the amount for your batch with the "
                     "Accounting Office.")
    return "\n".join(lines) + "\n" + " ".join(notes) + f"\n\nSource: {FEE_SOURCE}", True


def count_text(rows: list[dict], question: str) -> tuple[str, bool]:
    text = normalize_text(question)
    program, year = find_program(text.split(), text), find_year(text)
    what = (_label(program) if program else "PGPC") + (f" {YEAR_NAMES[year]}" if year else "")
    handbook = ("The only figure in the PGPC Student Handbook is from the opening year: PGPC opened in 2024 to more than "
                "nine hundred students, 80% of them Garciano residents. ")
    specific = f" for {what}" if (program or year) else ""
    none = (f"I don't have the current number of enrolled students on file{specific}. " + handbook +
            f"For the current number, please ask the Office of the Registrar.\n\nSource: {COUNT_SOURCE}")

    def pick(p, y):
        return [r for r in rows if r["program"] == p and r["year_level"] == y]
    exact = pick(program, year)
    if exact:
        r = exact[0]
        return _one(what, r), True
    if program and year is None:
        by_year = {r["year_level"]: r for r in rows if r["program"] == program and r["year_level"]}
        if by_year:
            total = sum(r["students"] for r in by_year.values())
            lines = [f"{_label(program)} has {total:,} enrolled students in the records I have"
                     + (f" ({_as_of(list(by_year.values())[0])})." if _as_of(list(by_year.values())[0]) else ".")]
            lines += [f"- {YEAR_NAMES[y]}: {r['students']:,}" for y, r in sorted(by_year.items())]
            if len(by_year) < 4:
                lines.append("Some year levels have not been added yet.")
            return "\n".join(lines) + f"\n\nSource: {COUNT_SOURCE}", True
    if year and program is None:
        per_prog = {r["program"]: r for r in rows if r["year_level"] == year and r["program"]}
        if per_prog:
            total = sum(r["students"] for r in per_prog.values())
            lines = [f"There are {total:,} {YEAR_NAMES[year]} students in the records I have."]
            lines += [f"- {p}: {r['students']:,}" for p, r in per_prog.items()]
            if len(per_prog) < len(PROGRAMS):
                lines.append("Some programs have not been added yet.")
            return "\n".join(lines) + f"\n\nSource: {COUNT_SOURCE}", True
    if program is None and year is None:
        overall = [r for r in rows if not r["program"] and not r["year_level"]]
        if overall:
            return _one("PGPC", overall[0]), True
        per_prog = {}
        for r in rows:
            if r["program"] and not r["year_level"]:
                per_prog[r["program"]] = r
        for p in PROGRAMS:
            ys = [r for r in rows if r["program"] == p and r["year_level"]]
            if p not in per_prog and ys:
                per_prog[p] = {"students": sum(r["students"] for r in ys), "as_of": ys[0].get("as_of")}
        if per_prog:
            total = sum(r["students"] for r in per_prog.values())
            lines = [f"PGPC has {total:,} enrolled students in the records I have."]
            lines += [f"- {p}: {r['students']:,}" for p, r in per_prog.items()]
            if len(per_prog) < len(PROGRAMS):
                lines.append("Some programs have not been added yet.")
            return "\n".join(lines) + f"\n\nSource: {COUNT_SOURCE}", True
    if program and year is None:
        tot = [r for r in rows if r["program"] == program and not r["year_level"]]
        if tot:
            return _one(what, tot[0]), True
    return none, False


def _as_of(r: dict) -> str:
    return f"as of {r['as_of']}" if r.get("as_of") else ""


def _one(what: str, r: dict) -> str:
    when = _as_of(r)
    note = f" {r['note']}" if r.get("note") else ""
    return f"{what}: {r['students']:,} enrolled students" + (f" ({when})" if when else "") + f".{note}\n\nSource: {COUNT_SOURCE}"


# --------------------------------------------------------------------------- thin database readers
def load_fee_rows(db) -> list[dict]:
    from sqlalchemy import select
    from app.models import TuitionFee
    return [dict(program=f.program, residency=f.residency, year_level=f.year_level, semester=f.semester,
                 academic_year=f.academic_year, amount=f.amount) for f in db.scalars(select(TuitionFee))]


def load_count_rows(db) -> list[dict]:
    from sqlalchemy import select
    from app.models import EnrollmentCount
    return [dict(program=c.program, year_level=c.year_level, students=c.students, as_of=c.as_of, note=c.note)
            for c in db.scalars(select(EnrollmentCount))]


def load_procedures(db) -> tuple[str | None, str | None]:
    """The procedure texts as the admin last edited them in the FAQ list (None = use the built-in text)."""
    from sqlalchemy import select
    from app.models import FAQ
    new = sem2 = None
    for f in db.scalars(select(FAQ).where(FAQ.category == PROCEDURE_CATEGORY, FAQ.is_active.is_(True))):
        kw = (f.keywords or "").lower()
        if "2nd sem" in kw or "continuing" in kw:
            sem2 = f.answer
        elif "incoming" in kw:
            new = f.answer
    return new, sem2
