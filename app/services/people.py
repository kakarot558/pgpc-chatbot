"""Who-is-the-<role> questions:  "who is the president of PGPC", "who is utility staff", "who are the faculty".

Why the old answer failed
-------------------------
Employee questions were answered by matching words against employee NAMES. But
  * the 2026 roster has only names and a group (Faculty / Administrative Personnel), no job titles, and
  * the handbook already names the officials (College President, Mayor, Vice Mayor, Board of Trustees),
    but nobody connected that text to a "who is ..." question.
So "who is the president of PGPC" and "who is utility staff" both ended with "I couldn't find that person".

What this module does (no language model, only stored PGPC text, so nothing is invented):
  1. Reads the officials the handbook names (signature blocks, the Board of Trustees page, and the sentence that
     names the College President) and links each one to the employee roster when the name matches.
  2. Looks for a role in the employee records: the position name and the roster note (e.g. "Kuya Guard").
  3. Answers group questions ("who are the faculty", "how many administrative personnel") with the full list.
  4. When the role is simply not on file, says exactly what IS on file and how to get it added, instead of a
     dead end. A question about somebody else's country ("president of the United States") is left alone.

Pure functions first (no database); `people_answer` is the only function that touches the database.
"""
import re
from dataclasses import dataclass, field

from app.utils.text_cleaner import normalize_text, strip_accents

# --------------------------------------------------------------------------- vocabulary
TITLE_RE = r"(?:Hon|Dr|Mr|Ms|Mrs|Engr|Atty|Prof|Sir|Madam)\.?"
# Words that only help to ask the question; they are not the role.
FILLER = {
    "the", "a", "an", "our", "all", "any", "of", "in", "at", "for", "from", "here", "is", "are", "was", "were", "s",
    "po", "ho", "please", "pls", "kindly", "me", "you", "can", "could", "tell", "show", "give", "list", "name", "names",
    "know", "want", "to", "i", "we", "us", "and", "or", "currently", "current", "now", "today", "right", "who", "whos",
    "whom", "what", "which", "that", "this", "do", "does", "have", "has", "there", "about", "info", "information",
    "details", "detail", "member", "members", "people", "person", "persons", "worker", "workers", "staff", "staffs",
    "employee", "employees", "personnel", "mga", "ang", "ng", "sino", "oic", "acting",
}
PGPC_WORDS = {"pgpc", "college", "school", "campus", "padre", "garcia", "polytechnic", "our", "here", "this", "your"}
# Words that, together with the filler, make a question a *role* question (not a person's name).
ROLE_VOCAB = {
    "president", "vice", "mayor", "chairperson", "chairman", "chair", "trustee", "trustees", "board", "dean", "deans",
    "director", "head", "registrar", "cashier", "librarian", "nurse", "doctor", "physician", "dentist", "guidance",
    "counselor", "counsellor", "guard", "guards", "security", "utility", "janitor", "janitress", "maintenance",
    "cleaner", "custodian", "driver", "secretary", "treasurer", "auditor", "officer", "coordinator", "adviser",
    "advisor", "manager", "clerk", "faculty", "teacher", "teachers", "professor", "professors", "instructor",
    "instructors", "admin", "administrative", "administrator", "leader", "boss", "principal", "prefect", "discipline",
    "accountant", "bookkeeper", "electrician", "plumber", "gardener", "canteen", "clinic", "library", "it", "office",
    "municipal", "academic", "affairs", "vpaa", "osa", "chief", "supervisor", "marshal", "marshals", "kuya", "ate",
    "non", "teaching", "secretary", "vp", "vpaa", "finance", "administration",
    "program", "chairs", "assistant", "vpaf", "hr", "accounting", "staff", "research", "extension", "criminology",
    "ccba", "bscs", "bsma", "bpa", "crim", "reasearch", "nurse", "counselor", "cashiers", "librarians", "deans",
}
# Student words -> the words used in the records.
ALIASES: dict[str, list[str]] = {
    "admin": ["admin", "administration"],
    "crim": ["crim", "criminology"],
    "ccba": ["ccba"],
    "utility": ["utility", "janitor", "janitress", "maintenance", "cleaner", "custodian", "utilityman"],
    "janitor": ["utility", "janitor", "janitress", "maintenance", "cleaner", "custodian"],
    "janitress": ["utility", "janitor", "janitress", "maintenance", "cleaner"],
    "maintenance": ["utility", "maintenance", "janitor"],
    "cleaner": ["utility", "janitor", "cleaner", "custodian"],
    "guard": ["guard", "security"],
    "guards": ["guard", "security"],
    "security": ["guard", "security"],
    "teacher": ["faculty", "teacher", "instructor", "professor"],
    "teachers": ["faculty", "teacher", "instructor", "professor"],
    "instructor": ["faculty", "instructor", "teacher"],
    "instructors": ["faculty", "instructor", "teacher"],
    "professor": ["faculty", "professor", "teacher"],
    "professors": ["faculty", "professor", "teacher"],
    "counselor": ["counselor", "counsellor", "guidance"],
    "counsellor": ["counselor", "counsellor", "guidance"],
    "librarian": ["librarian"],
    "nurse": ["nurse", "physician", "doctor"],
}
# "head / leader / boss of the college" means the College President.
HEAD_WORDS = {"head", "leader", "boss", "principal", "chief"}
LEAD_VERBS = {"leads", "lead", "runs", "run", "heads", "manages", "manage", "charge", "owns", "oversees"}

GROUPS = {
    "Faculty": {"faculty", "teacher", "teachers", "professor", "professors", "instructor", "instructors"},
    "Administrative Personnel": {"admin", "administrative", "administration", "administrator", "nonteaching",
                                 "non-teaching"},
}
GENERIC_STAFF = {"staff", "staffs", "employee", "employees", "personnel", "people"}
MAX_LIST = 80
# Words after "who" that start a rule question, not a role question ("who can borrow books").
WHO_RULE_WORDS = {"can", "may", "should", "shall", "will", "must", "needs", "need", "are", "is", "do", "does"}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _fold(text: str) -> str:
    return normalize_text(text)


# --------------------------------------------------------------------------- reading the question
@dataclass
class RoleQuery:
    role: list[str]               # role words, e.g. ["utility"] or ["vice", "mayor"]
    qualifier: list[str]          # what follows "of / in / at", e.g. ["pgpc"] or ["united", "states"]
    plural: bool = False
    count: bool = False           # "how many ..."
    text: str = ""                # the role as the student wrote it, for the reply
    contact: str = ""             # "email" / "contact number" when the student wants a contact detail of that role


_REQUEST_PREFIXES = [["please"], ["pls"], ["can", "you"], ["could", "you"], ["tell", "me"], ["show", "me"],
                     ["give", "me"], ["i", "want", "to", "know"], ["i", "would", "like", "to", "know"],
                     ["what", "is"], ["what", "are"], ["name", "of"], ["names", "of"], ["list", "of"], ["name"],
                     ["names"], ["list"], ["the", "name", "of"]]


def _strip_request(words: list[str]) -> list[str]:
    """'name of the president of pgpc' -> 'the president of pgpc'; 'tell me the dean' -> 'the dean'."""
    changed = True
    while changed:
        changed = False
        for prefix in _REQUEST_PREFIXES:
            if words[:len(prefix)] == prefix and len(words) > len(prefix):
                words, changed = words[len(prefix):], True
    return words


def parse_role_question(question: str) -> RoleQuery | None:
    """Returns the role the student asks about, or None when the question is not about a person's role."""
    words = _fold(question).split()
    words = [x for w in words for x in (["who", "is"] if w == "whos" else ["who", "are"] if w == "whore" else [w])]
    if not words:
        return None
    for a, b in zip(words, words[1:]):
        if b in {"list", "lister", "listers", "honor", "honors", "scholar", "scholars"} and a in {"deans", "dean", "presidents", "president"}:
            return None                                   # "dean's list" / "president's list": recognition lists, not people
    count = words[:2] == ["how", "many"]
    if "who" in words:
        i = words.index("who")
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if nxt in WHO_RULE_WORDS and nxt not in {"is", "are"}:
            return None                                   # "who can borrow", "who may enroll" -> rules, not people
        rest = words[i + 1:]
        plural = nxt == "are"
    elif count:
        rest, plural = words[2:], True
    else:
        if words[0] in {"where", "when", "why", "which"} or (words[0] == "how" and not count):
            return None                                   # location / time / procedure questions are not role questions
        rest, plural = words, False
        rest = _strip_request(rest)
    if "vpaa" in rest:
        rest = [x for w in rest for x in (["vice", "president", "academic", "affairs"] if w == "vpaa" else [w])]
    if set(rest) & LEAD_VERBS and not set(rest) & ROLE_VOCAB:
        return RoleQuery(role=["president"], qualifier=["pgpc"], plural=False, count=False, text="president")
    joined = " ".join(rest)
    joined = re.sub(r"\b(vice president|vp)\s+for\s+", "vice president ", joined)
    joined = re.sub(r"\b(?:the\s+)?(?:members?\s+of\s+the\s+)?board\s+of\s+(?:trustees|directors|regents)\b", "trustees", joined)
    rest = joined.split()
    # "president of pgpc" / "head of the registrar office": the role comes before of/in/at, the qualifier after
    role, qualifier, seen_split = [], [], False
    for w in rest:
        if not seen_split and w in {"of", "in", "at", "for", "from", "under", "sa"} and role:
            seen_split = True
            continue
        (qualifier if seen_split else role).append(w)
    # "pgpc president": pgpc inside the role part is a qualifier
    if not seen_split and any(w in PGPC_WORDS for w in role):
        qualifier = [w for w in role if w in PGPC_WORDS]
    shown = [w for w in role if w not in {"the", "a", "an", "our", "all", "any", "po", "ho", "please", "pls", "mga",
                                           "ang", "ng", "is", "are", "was", "s", "who", "list", "names", "name"}
             and w not in PGPC_WORDS]
    role = [w for w in role if w not in FILLER and w not in PGPC_WORDS]
    if not role and shown and all(w in GENERIC_STAFF for w in shown):
        role = shown                                       # "who are the staff": the generic word IS the question
    if count:
        # "how many faculty does pgpc have": drop the verbs that follow the role
        role = [w for w in role if w not in {"does", "do", "have", "has", "are", "there"}]
    plural = plural or any(w.endswith("s") and w[:-1] in ROLE_VOCAB for w in role) or "are" in rest[:1]
    contact = {"email", "emails", "contact", "number", "phone", "telephone", "mobile", "cellphone"}
    if role and set(role) <= contact and qualifier:
        # "what is the email of the president": the role is in the qualifier, the contact word is the request
        role, qualifier, asked = [w for w in qualifier if w not in FILLER and w not in PGPC_WORDS], ["pgpc"], role
        if not role:
            return None
        return RoleQuery(role=role, qualifier=qualifier, plural=False, count=False, text=" ".join(role),
                         contact=" ".join(asked))
    if not role:
        return None
    return RoleQuery(role=role, qualifier=[w for w in qualifier if w not in FILLER or w in PGPC_WORDS],
                     plural=plural, count=count,
                     text="Board of Trustees" if "trustees" in role else " ".join(shown or role))


CAMPUS_PLACES = {"library", "clinic", "canteen", "gym", "gymnasium", "laboratory", "lab", "registrar", "cashier",
                 "guidance", "admission", "admissions", "accounting", "bookstore", "research", "extension", "osa",
                 "saco", "affairs", "department", "faculty", "ict", "computer", "nstp", "ojt", "security", "office",
                 "offices", "center", "unit", "section", "building"}


def is_pgpc_qualifier(qualifier: list[str], office_words: set[str] | None = None) -> bool:
    """Empty or school words only. 'of the united states' or 'of batangas' is somebody else's question."""
    rest = [w for w in qualifier if w not in FILLER and w not in PGPC_WORDS]
    if not rest:
        return True
    return set(rest) <= ((office_words or set()) | CAMPUS_PLACES)


def looks_like_role(role: list[str]) -> bool:
    """Every word is a known role word, so 'who is joy abu' (a name) is not mistaken for a role."""
    return bool(role) and all(w in ROLE_VOCAB or _stem(w) in ROLE_VOCAB for w in role) \
        and any(w not in {"non", "teaching", "kuya", "ate"} for w in role)


# --------------------------------------------------------------------------- officials named in the handbook
@dataclass
class Official:
    name: str                              # as printed, e.g. "Dr. Nino J. Vinas"
    roles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # "designated since March 1, 2024"
    key: tuple[str, str] = ("", "")

    def role_line(self) -> str:
        return ", ".join(self.roles)


_NAME_CHARS = r"[A-Z][A-Za-z.\-ñÑ']*"
_TITLED_LINE = re.compile(rf"^\s*(?:\[?\s*sign\s*\]?\s*)?({TITLE_RE}\s+{_NAME_CHARS}(?:\s+{_NAME_CHARS}){{1,4}})\s*$")
_SENTENCE = re.compile(
    rf"({TITLE_RE}\s+{_NAME_CHARS}(?:\s+{_NAME_CHARS}){{1,4}})\s+(?:was|is)\s+the\s+(?:first\s+)?(?:designated\s+)?"
    r"(?P<role>[^.]{5,120}?)\s+since\s+(?P<since>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
_PLAIN_NAME = re.compile(rf"^{_NAME_CHARS}(?:\s+{_NAME_CHARS}){{1,4}}(?:,\s*[A-Z]{{2,5}})?$")
_ROLE_WORD = re.compile(r"\b(President|Dean|Secretary|Director|Registrar|Treasurer|Chairperson|Coordinator|Trustees|"
                        r"Head|Officer|Librarian|Nurse|Physician)\b")
_TITLE_SMALL_WORDS = {"for", "of", "and", "on", "the", "in", "to"}


def _looks_like_job_title(line: str) -> bool:
    """'College Dean' / 'Vice President for Administration and Finance' yes; a sentence that mentions a President no."""
    line = line.strip()
    if not _ROLE_WORD.search(line) or len(line) > 70 or re.search(r"[,:;]$|\.$", line):
        return False
    return all(w[0].isupper() or w in _TITLE_SMALL_WORDS for w in line.split() if w[0].isalpha())


_STOP_LINE = re.compile(r"^(page\b|-{3,}|_{3,}|\[?image|\{?sign|chapter\b|table of contents)", re.I)


def _name_key(name: str) -> tuple[str, str]:
    bare = re.sub(rf"^{TITLE_RE}\s+", "", name.strip())
    parts = [p for p in strip_accents(bare).lower().replace(".", " ").split() if p]
    if not parts:
        return ("", "")
    last = parts[-1].split("-")[-1]
    return (parts[0], last)


def _role_atoms(text: str) -> list[str]:
    text = " ".join(text.split())
    atoms = []
    for chunk in re.split(r",|/|;", text):
        # split "Vice Mayor and Chairperson of ..." but keep "Vice President for Administration and Finance" whole
        for part in re.split(r"\s+and\s+(?=(?:[A-Z]\w*\s+){0,3}(?:President|Dean|Secretary|Director|Registrar|"
                             r"Treasurer|Chairperson|Coordinator|Trustees|Head|Officer|Mayor|Chair)\b)", chunk):
            part = part.strip(" .,")
            if part:
                atoms.append(part)
    keep, seen = [], set()
    for a in atoms:
        ta = frozenset(_stem(w) for w in _fold(a).split())
        if ta in seen or any(ta < frozenset(_stem(w) for w in _fold(b).split()) for b in atoms):
            continue                                   # a repeat, or a shorter copy of a longer title
        seen.add(ta)
        keep.append(a)
    return keep


def parse_officials(text: str) -> list[Official]:
    """Officials the handbook itself names. Signature blocks and the Board of Trustees page look like
        Dr. Nino J. Vinas
        College President,
        Board of Trustees
    and one sentence names the President: 'Dr. Nino J. Vinas was the first designated College President ... since ...'"""
    found: dict[tuple[str, str], Official] = {}

    def add(name: str, roles: list[str], note: str | None = None) -> None:
        key = _name_key(name)
        if not key[0]:
            return
        off = found.setdefault(key, Official(name=name, key=key))
        if len(name) > len(off.name):
            off.name = name
        for r in roles:
            if r and r.lower() not in {x.lower() for x in off.roles}:
                off.roles.append(r)
        off.roles = _role_atoms(", ".join(off.roles)) if len(off.roles) > 1 else off.roles
        if note and note not in off.notes:
            off.notes.append(note)

    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        m = _TITLED_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        name, role_lines, j = m.group(1).strip(), [], i + 1
        while j < len(lines) and len(role_lines) < 5:
            s = lines[j].strip()
            if not s or _STOP_LINE.match(s) or _TITLED_LINE.match(s):
                break
            role_lines.append(s)
            j += 1
        if role_lines:
            add(name, _role_atoms(" ".join(role_lines)))
        i = max(j, i + 1)

    # People printed without an honorific: "Joy H. Abu" followed by "College Dean"
    for k in range(len(lines) - 1):
        a, b = lines[k].strip(), lines[k + 1].strip()
        if _PLAIN_NAME.match(a) and not _ROLE_WORD.search(a) and _looks_like_job_title(b) \
                and len(a.split()[0].rstrip(".")) > 1 and not _TITLED_LINE.match(a):
            add(re.sub(r",\s*[A-Z]{2,5}$", "", a), _role_atoms(b))

    flat = " ".join((text or "").split())
    for m in _SENTENCE.finditer(flat):
        add(m.group(1), _role_atoms(m.group("role")), f"designated since {m.group('since')}")
    return [o for o in found.values() if o.roles]


# --------------------------------------------------------------------------- matching a role
def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in _fold(text).split() if w}


_WEAK = {"municipal", "college", "pgpc", "of", "the", "for", "on", "in"}


def role_matches(atom: str, query_role: list[str]) -> bool:
    """'president' matches 'College President' but not 'Vice President for Academic Affairs';
    'vice mayor' matches only the Vice Mayor; 'board of trustees' matches every trustee."""
    q = {_stem(w) for w in query_role if w not in FILLER or w in {"of"}}
    q = {w for w in q if w not in {"of"}}
    if HEAD_WORDS & q:
        q = (q - HEAD_WORDS) | {"president"}
    a = _tokens(atom)
    if not q or not q <= a:
        return False
    if "vice" in a and "vice" not in q:
        return False
    return True


def find_officials(officials: list[Official], query_role: list[str]) -> list[tuple[Official, list[str]]]:
    out = []
    for off in officials:
        mine = [r for r in off.roles if role_matches(r, query_role)]
        if mine:
            out.append((off, mine))
    return out


# --------------------------------------------------------------------------- writing the answers
def display_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def write_officials(matches: list[tuple[Official, list[str]]], query: RoleQuery, roster_names: dict) -> str:
    lines: list[str] = []
    if len(matches) == 1:
        off, mine = matches[0]
        role = mine[0]
        suffix = " of PGPC" if role.lower().startswith("college") else ""
        lines.append(f"{display_name(off.name)} is the {role}{suffix}.")
        more = [r for r in off.roles if r not in mine]
        if more:
            lines.append("Also listed as: " + ", ".join(more) + ".")
        if off.notes:
            lines.append("The handbook says: " + "; ".join(off.notes) + ".")
    else:
        lines.append(f'The PGPC Student Handbook lists these people for "{query.text}":')
        for off, mine in matches:
            lines.append(f"- {display_name(off.name)}: {', '.join(off.roles)}")
    for off, _ in matches[:6]:
        emp = roster_names.get(off.key)
        if emp:
            lines.append(f"Employee record: {emp}.")
    return "\n".join(lines)


NOT_ON_FILE = ("I don't have a record of who the {role} {verb}. {have} Since there are no job titles, I can't tell who "
               "holds {that}.\n\n{next}")
ADMIN_HINT = ("If you are the PGPC admin: add the position \"{title}\" and assign it to the employee in the admin "
              "dashboard (Positions, then Employees). After that I can answer this question right away.")


def roster_summary(counts: dict[str, int]) -> str:
    if not counts:
        return "I have no employee records yet."
    parts = [f"{n} under {g}" for g, n in counts.items()]
    return ("The 2026 employee roster lists " + " and ".join(parts) +
            " (" + ("Faculty and Administrative Personnel are the only groups" if len(parts) > 1 else "one group") +
            "), with names only and no job titles.")


# --------------------------------------------------------------------------- database part
@dataclass
class PeopleResult:
    text: str
    sources: list[dict]
    found: bool = True
    incomplete: bool = False


def _person_name(e) -> str:
    return " ".join(p for p in (e.first_name, e.middle_name, e.last_name) if p and not p.startswith("["))


_NOTE_RE = re.compile(r"Roster note:\s*\(([^)]*)\)", re.I)
_PLACEHOLDER = re.compile(r"\[ADMIN:[^\]]*\]")


def roster_note(e) -> str:
    m = _NOTE_RE.search(e.description or "")
    return m.group(1).strip().title() if m else ""


def employee_role_text(e) -> str:
    desc = _PLACEHOLDER.sub(" ", e.description or "")
    desc = re.sub(r"Listed under '[^']*' in the PGPC 2026 employee roster\.?|Roster note:\s*\([^)]*\)\.?", " ", desc)
    parts = [e.position.name if e.position else "", roster_note(e), desc, e.office.name if e.office else ""]
    return " ".join(p for p in parts if p)


def employees_for_role(employees: list, query_role: list[str]) -> list:
    """Employees whose position / roster note / office matches every role word (or a synonym of it)."""
    words = [w for w in query_role if w not in GENERIC_STAFF and w not in FILLER]
    if not words:
        return []
    out = []
    for e in employees:
        have = _tokens(employee_role_text(e))
        if all(have & {_stem(a) for a in ALIASES.get(w, ALIASES.get(_stem(w), [w]))} | ({_stem(w)} & have)
               for w in words):
            out.append(e)
    return out


def group_of(query_role: list[str]) -> str | None:
    q = {w for w in query_role if w not in GENERIC_STAFF and w not in {"non", "teaching"}}
    for name, words in GROUPS.items():
        if q and q <= words:
            return name
    return None


def _employee_line(e, hide_group: str | None = None) -> str:
    pos = e.position.name if e.position else ""
    bits = [b for b in ((pos if pos != hide_group else ""), (e.office.name if e.office else ""),
                        roster_note(e)) if b]
    return f"- {_person_name(e)}" + (f" ({'; '.join(bits)})" if bits else "")


def write_employees(found: list, query: RoleQuery) -> str:
    if len(found) == 1:
        e = found[0]
        lines = [f"Here is what I have on {_person_name(e)}:"]
        for label, value in (("Group / position", e.position.name if e.position else ""),
                             ("Office", e.office.name if e.office else ""), ("Roster note", roster_note(e)),
                             ("Email", e.email), ("Contact number", e.contact_number)):
            if value:
                lines.append(f"- {label}: {value}")
        return "\n".join(lines)
    shown = found[:MAX_LIST]
    lines = [f'I found {len(found)} people for "{query.text}":'] + [_employee_line(e) for e in shown]
    if len(found) > len(shown):
        lines.append(f"...and {len(found) - len(shown)} more.")
    lines.append("Ask about one of them by name for more details.")
    return "\n".join(lines)


GROUP_TITLES = {"Faculty", "Administrative Personnel"}
SUBORDINATE = {"secretary", "assistant", "deputy", "staff"}


def _real_title(e) -> bool:
    """A job title the admin or the personnel list gave, not a roster group heading."""
    return bool(e.position and e.position.name not in GROUP_TITLES)


def _is_head_title(e, query_role: list[str]) -> bool:
    """'Secretary of the College President' is not the president, 'Assistant Librarian' is not the librarian, and
    'Vice President for ...' is not the president."""
    first = (_fold(e.position.name).split() or [""])[0]
    if first in SUBORDINATE and first not in {_stem(w) for w in query_role} and first not in query_role:
        return False
    if ({"president"} | HEAD_WORDS) & {_stem(w) for w in query_role} and "vice" not in query_role:
        return role_matches(e.position.name, query_role)
    return True


def floor_text(floor) -> str:
    f = str(floor or "").strip()
    return f"Floor {f}" if f.isdigit() else f


def room_text(room) -> str:
    r = str(room or "").strip()
    return f"Room {r}" if re.fullmatch(r"\d+[A-Za-z]?", r) else r


def write_titled(found: list, query: RoleQuery) -> str:
    def where(e) -> str:
        if not e.office:
            return ""
        loc = ", ".join(x for x in (floor_text(e.office.floor), e.office.building, room_text(e.office.room_number)) if x)
        return e.office.name + (f", located at: {loc}" if loc else "")
    if len(found) == 1:
        e = found[0]
        title = e.position.name
        text = f"{_person_name(e)} is the {title}" + ("" if " of " in title or " for " in title else " of PGPC") + "."
        if where(e):
            text += f"\nOffice: {where(e)}."
        return text + "\n\nSource: PGPC employee records"
    lines = [f'These are the people I have for "{query.text}":']
    for e in found[:MAX_LIST]:
        lines.append(f"- {_person_name(e)}: {e.position.name}")
    lines.append("Ask about one of them by name for more details.")
    return "\n".join(lines) + "\n\nSource: PGPC employee records"


def people_answer(db, question: str, intent_name: str | None = None) -> PeopleResult | None:
    question = re.sub(r"\b(?:new|current|present|latest|existing|newest|bagong)\s+(?=(?:college\s+)?president\b)", "", question or "", flags=re.I)
    question = re.sub(r"\bwho\s+(?:heads|leads|runs|manages)\s+(?:the\s+)?(?!pgpc|school|college)", "head of ", question or "", flags=re.I)
    question = re.sub(r"\bhead of (?:the )?(?:pgpc|school|college|campus|polytechnic college)\b", "president", question or "", flags=re.I)
    """None means: this is not a role question, let the normal answer path handle it."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from app.models import Employee, HandbookSection, Office

    q = parse_role_question(question)
    if q is None:
        return None
    offices = list(db.scalars(select(Office)))
    office_words = {w for o in offices for w in _fold(o.name).split()} - FILLER - {"office", "of"}
    employees = list(db.scalars(select(Employee).options(joinedload(Employee.position), joinedload(Employee.office))))
    extra = [w for w in q.qualifier if w not in FILLER and w not in PGPC_WORDS]
    base = [] if (set(q.role) <= {"head", "heads", "chief"}) else q.role          # "head of the registrar office"
    extra_t = [{"library": "librarian"}.get(w, w) for w in extra if w not in {"office", "department", "unit"}] \
        if not base else extra
    titled = ([e for e in employees_for_role(employees, base + extra_t) if _real_title(e)]
              if extra_t else [])
    extra = extra_t
    if titled:
        # "program chair of BSCS", "director of research and extension": the qualifier is part of a job title on file
        q = RoleQuery(role=base + extra, qualifier=[], plural=q.plural, count=q.count, text=" ".join(base + extra),
                      contact=q.contact)
    elif not is_pgpc_qualifier(q.qualifier, office_words):
        return None                                             # "president of the united states" is somebody else's question
    elif not looks_like_role(q.role):
        return None                                             # a person's name: the normal path handles it

    counts: dict[str, int] = {}
    for e in employees:
        if e.position:
            counts[e.position.name] = counts.get(e.position.name, 0) + 1
    emp_source = {"type": "employee", "source": "PGPC employee records"}

    # 1) a whole group: "who are the faculty", "how many administrative personnel"
    group = group_of(q.role)
    generic_only = all(w in GENERIC_STAFF or w in FILLER for w in q.role)
    if group and not q.contact:
        members = [e for e in employees if e.position and e.position.name == group]
        if q.count:
            return PeopleResult(f"The PGPC employee records list {len(members)} people under {group}.",
                                [dict(emp_source, id=None, title=group)])
        if members:
            lines = [f"{group} ({len(members)} people listed in the PGPC employee records):"]
            lines += [_employee_line(e, group) for e in members[:MAX_LIST]]
            if len(members) > MAX_LIST:
                lines.append(f"...and {len(members) - MAX_LIST} more.")
            lines.append("The roster records names and groups only; ask about a person by name for more.")
            return PeopleResult("\n".join(lines), [dict(emp_source, id=None, title=group)], incomplete=True)

    # 1b) "who is the head of the library": a known place, but no person is recorded for it
    place = [w for w in q.qualifier if w in CAMPUS_PLACES or w in office_words]
    if place and set(q.role) & (HEAD_WORDS | {"head", "director", "in", "charge", "incharge"}):
        shown = " ".join(place)
        return PeopleResult(
            f"I don't have a record of who heads the {shown} yet. You can ask me where it is, or check with the "
            f"concerned PGPC office.", [], found=False)

    # 1c) a job title in the employee records ("OIC College President", "Librarian"): the school's own list comes first
    held = [e for e in employees_for_role(employees, q.role) if _real_title(e) and _is_head_title(e, q.role)]
    if held and not q.count and not q.contact:
        return PeopleResult(write_titled(held, q), [dict(emp_source, id=e.id, title=_person_name(e)) for e in held[:5]],
                            incomplete=any(not e.office_id for e in held))
    if held and q.contact and len(held) == 1:               # "email of the president": the person who holds the title now
        e = held[0]
        who = f"{_person_name(e)} ({e.position.name})"
        wants_email = "email" in q.contact
        value = e.email if wants_email else e.contact_number
        what = "email" if wants_email else "contact number"
        text = (f"The {what} of {who} is {value}." if value
                else f"I don't have {'an email address' if wants_email else 'a contact number'} for {who} on file yet. "
                     "Please check with the concerned PGPC office.")
        return PeopleResult(text, [dict(emp_source, id=e.id, title=_person_name(e))], found=bool(value))

    # 2) officials the handbook names
    sections = list(db.scalars(select(HandbookSection)))
    officials: list[Official] = []
    seen = set()
    for s in sections:
        for off in parse_officials(s.content or ""):
            if off.key in seen:
                for o in officials:
                    if o.key == off.key:
                        o.roles = _role_atoms(", ".join(o.roles + off.roles))
                        o.notes += [n for n in off.notes if n not in o.notes]
                        if len(off.name) > len(o.name):
                            o.name = off.name
            else:
                seen.add(off.key)
                officials.append(off)
    matches = find_officials(officials, q.role)
    by_key = {(strip_accents(e.first_name or "").lower().split(" ")[0] if e.first_name else "",
               strip_accents(e.last_name or "").lower()): e for e in employees}
    # the roster (current titles) beats the handbook: drop an official whose roster title is a different job
    matches = [m for m in matches
               if not (by_key.get(m[0].key) is not None and _real_title(by_key[m[0].key])
                       and not _is_head_title(by_key[m[0].key], q.role))]
    if matches and q.contact and len(matches) == 1:
        off = matches[0][0]
        emp = next((e for e in employees if (strip_accents(e.first_name or "").lower().split(" ")[0] if e.first_name
                                             else "", strip_accents(e.last_name or "").lower()) == off.key), None)
        who = f"{display_name(off.name)} ({matches[0][1][0]})"
        email, number = (emp.email if emp else None), (emp.contact_number if emp else None)
        wants_email = "email" in q.contact
        if wants_email and email:
            text = f"The email of {who} is {email}."
        elif not wants_email and number:
            text = f"The contact number of {who} is {number}."
        else:
            what = "an email address" if wants_email else "a contact number"
            text = (f"I don't have {what} for {who} on file yet. Please check with the concerned PGPC office.")
        srcs = ([dict(emp_source, id=emp.id, title=_person_name(emp))] if emp else []) + \
               [{"type": "handbook", "id": None, "title": display_name(off.name), "source": "PGPC Student Handbook"}]
        return PeopleResult(text, srcs, found=bool(email if wants_email else number))
    if q.contact and not matches:
        # "contact number of the registrar office" is an OFFICE question; only a single person can answer here
        if len(employees_for_role(employees, q.role)) != 1:
            return None
    if matches and not q.count:
        roster, roster_emp = {}, {}
        for e in employees:
            k = (strip_accents(e.first_name or "").lower().split(" ")[0] if e.first_name else "",
                 strip_accents(e.last_name or "").lower())
            roster[k] = f"{_person_name(e)}" + (f", {e.position.name}" if e.position else "")
            roster_emp[k] = e
        text = write_officials(matches, q, roster)
        text += "\n\nSource: PGPC Student Handbook (names of officials)"
        sources = [{"type": "handbook", "id": None, "title": display_name(matches[0][0].name),
                    "source": "PGPC Student Handbook"}]
        linked = roster_emp.get(matches[0][0].key) if len(matches) == 1 else None
        if linked is not None:                       # follow-ups ("what is his email") then use the employee record
            sources.insert(0, dict(emp_source, id=linked.id, title=_person_name(linked)))
        return PeopleResult(text, sources)

    # 3) employees by position / roster note ("utility staff", "security guard")
    found = employees_for_role(employees, q.role)
    if found:
        text = write_employees(found, q) + "\n\nSource: PGPC employee records"
        src = [dict(emp_source, id=e.id, title=_person_name(e)) for e in found[:5]]
        return PeopleResult(text, src, incomplete=any(not (e.office_id and e.position_id) for e in found))

    # 4) "who is the registrar": the office exists, the person is not on file
    role_words = {_stem(w) for w in q.role}
    for o in offices:
        if role_words and role_words <= {_stem(w) for w in _fold(o.name).split()}:
            return PeopleResult(
                f"I have a record of the {o.name}, but who the {q.text} is has not been added yet. "
                f"You can ask me where the {o.name} is, or check with the concerned PGPC office.", [], found=False)

    # 5) honest fallback: say what IS on file
    if generic_only:
        lines = ["These are the employee groups in the PGPC records:"] + \
                [f"- {g}: {n} people" for g, n in counts.items()] + \
                ["Ask me for one of them, for example \"who are the faculty\" or \"who are the administrative personnel\"."]
        return PeopleResult("\n".join(lines), [dict(emp_source, id=None, title="Employee groups")])
    have = roster_summary(counts)
    nxt = ("You can ask me about the people I do have, for example \"who are the administrative personnel\", "
           "\"who is the president of PGPC\" or \"who are the Board of Trustees\". " +
           ADMIN_HINT.format(title=" ".join(w.capitalize() for w in (q.text.split() or q.role))) +
           "\nYou can also check with the concerned PGPC office.")
    return PeopleResult(NOT_ON_FILE.format(
        role=q.text, have=have, next=nxt, verb="are" if q.plural else "is",
        that="those positions" if q.plural else "that position"), [], found=False)
