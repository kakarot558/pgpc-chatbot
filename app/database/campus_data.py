"""Job titles, office locations and rooms taken from the PGPC personnel list and the two hand-drawn floor plans.

Run once (safe to run again):   python -m app.database.apply_campus_data

Rules that keep the admin's own edits safe:
  * an employee's position is set only when it is empty or still a roster group heading ("Faculty",
    "Administrative Personnel"); a title the admin chose is never replaced;
  * an office or room gets its building, floor and room only where those are still empty;
  * nothing is deleted.

Floor plan reading (check it, then rename in the admin dashboard if the school calls the buildings something else):
  * Main Building: the L-shaped plan. The College Dean, VPAA and President offices are drawn under the "2ND FLOOR"
    label; every other room of that plan is under "GROUND FLOOR".
  * Building 2: the second plan (criminology rooms, Guidance, OSA). It has no floor label, so no floor is recorded.
  * "X" between two names on the plan means the two share one room.
"""
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, Office, Position, Room

MAIN = "White Building"
BLDG2 = "Yellow Building"
GROUND = "1st floor"
SECOND = "2nd floor"
# Names and floor wording an earlier version of this data used; stored records are renamed to the new ones.
OLD_BUILDINGS = {"Main Building": MAIN, "Building 2": BLDG2}
OLD_FLOORS = {"Ground floor": GROUND}

# ----------------------------------------------------------------------------- job titles
# (title, what the job is). Names follow the handwritten personnel list.
POSITIONS = {
    "OIC College President": "Officer-in-Charge of the College President of PGPC.",
    "Vice President for Academic Affairs (VPAA)": "Heads academic affairs of PGPC.",
    "Vice President for Administration and Finance (VPAF)": "Heads administration and finance of PGPC.",
    "Dean of Criminology": "Dean of the Criminology program.",
    "Dean of CCBA": "Dean of the College of Computing, Business and Administration (CCBA).",
    "Program Chair of Criminology": "Program Chair of the Criminology program.",
    "Program Chair of BSMA": "Program Chair of the BSMA program.",
    "Program Chair of BPA": "Program Chair of the BPA (Bachelor of Public Administration) program.",
    "Program Chair of BSCS": "Program Chair of the BS Computer Science (BSCS) program.",
    "Librarian": "Librarian of the College Library.",
    "Assistant Librarian": "Assistant to the Librarian of the College Library.",
    "Library Staff": "Staff of the College Library.",
    "HR / Cashier Staff": "Staff of the Human Resources and the Cashier's Office.",
    "HR Staff": "Staff of the Human Resources office.",
    "Accounting Staff": "Staff of the Accounting Office.",
    "Assistant Guidance Counselor": "Assistant to the guidance counselor of the Guidance Office.",
    "Secretary of the College President": "Secretary of the College President.",
    "OSA Staff": "Staff of the Office of Student Affairs (OSA).",
    "School Nurse": "School nurse of the College Clinic.",
    "College Registrar": "Registrar of PGPC; head of the Office of the Registrar.",
    "Director of Research and Extension": "Director of the Research and Extension office.",
    "Utility Staff": "Utility (maintenance and cleaning) staff of PGPC.",
}

# Titles an earlier version of this list gave that the newest Personnel Directory replaced.
OLD_CAMPUS_TITLES = {"Program Chair of BECEd"}

# (last name, first name starts with, title, office name or None). Spelling follows the 2026 employee roster.
ASSIGNMENTS = [
    ("Manalo", "Mark", "OIC College President", "Office of the College President"),
    ("Escamillas", "Nena", "Vice President for Academic Affairs (VPAA)", "Office of the Vice President for Academic Affairs (VPAA)"),
    ("Diaz", "Romy", "Vice President for Administration and Finance (VPAF)", "Office of the Vice President for Administration and Finance"),
    ("Abu", "Joy", "Dean of Criminology", "Office of the College Dean"),
    ("Aliwalas", "John Lester", "Dean of CCBA", "Office of the College Dean"),
    ("Abu", "Renan", "Program Chair of Criminology", None),
    ("Obra", "Shiela", "Program Chair of BSMA", None),
    ("Erlano", "Raul", "Program Chair of BPA", None),
    ("Sebuc", "Princess", "Program Chair of BSCS", None),
    ("Amparo", "Eunice", "Library Staff", None),
    ("Bayanin", "Catherine", "HR / Cashier Staff", "Cashier's Office"),
    ("Buya", "Jennifer", "Assistant Guidance Counselor", "Guidance Office"),
    ("Carpio", "Zara", "HR Staff", "Human Resources (HR) Office"),
    ("Contreras", "John Paul", "Librarian", None),
    ("Coronel", "Maria Priscilla", "Assistant Librarian", None),
    ("Gonzales", "Hazel", "Secretary of the College President", "Office of the College President"),
    ("Laresma", "Leo", "OSA Staff", "Office of Student Affairs (OSA)"),
    ("Mangurali", "Aldrin", "Accounting Staff", "Accounting Office"),
    ("Padua", "Anthony", "School Nurse", None),
    ("Solis", "Nicky", "College Registrar", "Office of the Registrar"),
    ("Viñas", "Niño", "Director of Research and Extension", "Research and Extension Office"),
    ("Balingit", "Daisy", "Utility Staff", None),
    ("Benedicto", "Reymundo", "Utility Staff", None),
    ("Sulabo", "Nedy", "Utility Staff", None),
    ("Valencia", "Reynaldo", "Utility Staff", None),
]
# People on the personnel list who are not in the 2026 roster file: (first, middle, last, note).
NEW_PEOPLE = [
    ("Mark Lester", None, "Manalo", "Atty. Mark Manalo, from the handwritten PGPC personnel list."),
    ("Romy C.", None, "Diaz", "Mr. Romy C. Diaz, LPT, MPA, from the handwritten PGPC personnel list."),
]

# ----------------------------------------------------------------------------- offices
# (name, building, floor, shares a room with, what it does or None to keep the text already stored)
OFFICES = [
    ("Office of the College President", MAIN, SECOND, None, "Office of the College President.", "OIC President"),
    ("Office of the Vice President for Academic Affairs (VPAA)", MAIN, SECOND, None,
     "Office of the Vice President for Academic Affairs (VPAA).", "VPAA"),
    ("Office of the College Dean", MAIN, SECOND, None, "Office of the College Dean.", "Office of College Deans"),
    ("Office of the Vice President for Administration and Finance", MAIN, GROUND, None,
     "Office of the Vice President for Administration and Finance (VPAF).", "Office of VP Administration & Finance"),
    ("Office of the Registrar", MAIN, GROUND, "the Admission Office", None, "Registrar Office & Admission Office"),
    ("Admission Office", MAIN, GROUND, "the Office of the Registrar", "Admission Office, handling student admission.",
     "Registrar Office & Admission Office"),
    ("Accounting Office", MAIN, GROUND, "the Cashier's Office and the Human Resources (HR) Office", "Accounting Office.",
     "Accounting Office & Cashier / HR"),
    ("Cashier's Office", MAIN, GROUND, "the Accounting Office and the Human Resources (HR) Office", None,
     "Accounting Office & Cashier / HR"),
    ("Human Resources (HR) Office", MAIN, GROUND, "the Accounting Office and the Cashier's Office",
     "Human Resources (HR) Office.", "Accounting Office & Cashier / HR"),
    ("Research and Extension Office", MAIN, GROUND, None, "Research and Extension Office.", "Research Extension"),
    ("NSTP Office", MAIN, GROUND, "the Property Management and General Services offices",
     "NSTP (National Service Training Program) Office.", "NSTP Office & Property Management Service"),
    ("Property Management Office", MAIN, GROUND, "the NSTP Office and the General Services Office",
     "Property Management Office.", "NSTP Office & Property Management Service"),
    ("General Services Office", MAIN, GROUND, "the NSTP Office and the Property Management Office",
     "General Services Office.", "NSTP Office & Property Management Service"),
    ("Office of Student Affairs (OSA)", BLDG2, GROUND, "the College Student Government (CSG) office", None, "OSA"),
    ("College Student Government (CSG) Office", BLDG2, GROUND, "the Office of Student Affairs (OSA)",
     "Office of the College Student Government (CSG).", "CSG"),
    ("Guidance Office", BLDG2, GROUND, None, None, "Guidance"),
    ("Management Information System (MIS) Office", BLDG2, GROUND, "Computer Lab 1",
     "Management Information System (MIS) Office.", "ComLab 1 & MIS"),
]
# Offices an earlier version put on a different floor: (name, floor it had). Moved only if it still has that floor.
OFFICE_FLOOR_FIXES = {n: SECOND for n in ("Office of Student Affairs (OSA)", "College Student Government (CSG) Office",
                                          "Guidance Office", "Management Information System (MIS) Office")}

# ----------------------------------------------------------------------------- rooms
# Rooms an earlier version of this list placed wrongly: (room number, floor it was given before). Moved only when the
# stored floor is still the old one, so a floor the admin corrected is left alone.
MOVED = {f"LR {n}": GROUND for n in "23456"}
MOVED.update({n: SECOND for n in ("Crime Lab 1", "Ballistic Room", "Com Lab 1", "Com Lab 2")})   # Yellow Building, 1st floor
# Rooms an earlier version made up from the first sketch; removed when they are still unchanged.
OLD_ROOMS = [("CR (Main Building, near the Lounge)", "Main Building"), ("CR (Main Building, near Lecture Room 1)", "Main Building"),
             ("CR (Main Building, near LR 2)", "Main Building"), ("CR (Building 2)", "Building 2"), ("CR (Building 2)", BLDG2),
             ("C.R Female (Ground floor)", MAIN), ("CR (Main Building, near LR 2)", MAIN),
             ("Interrogation and Observation Room", "Building 2"), ("Interrogation and Observation Room", BLDG2)]

# (room number / code, room name, building, floor, type)
ROOMS = [
    ("LR 1", "Lecture Room 1", MAIN, GROUND, "Lecture room"), ("LR 2", "Lecture Room 2", MAIN, SECOND, "Lecture room"),
    ("LR 3", "Lecture Room 3", MAIN, SECOND, "Lecture room"), ("LR 4", "Lecture Room 4", MAIN, SECOND, "Lecture room"),
    ("LR 5", "Lecture Room 5", MAIN, SECOND, "Lecture room"), ("LR 6", "Lecture Room 6", MAIN, SECOND, "Lecture room"),
    ("Com Lab 3", "Computer Laboratory 3", MAIN, GROUND, "Computer laboratory"),
    ("Faculty Room", "Faculty Room", MAIN, GROUND, "Faculty room"),
    ("Lounge", "Lounge", MAIN, GROUND, "Lounge"),
    ("C.R Female (1st floor)", "Female comfort room, 1st floor", MAIN, GROUND, "Comfort room"),
    ("C.R Male", "Male comfort room, 1st floor", MAIN, GROUND, "Comfort room"),
    ("PWD CR", "PWD comfort room 1", MAIN, GROUND, "Comfort room"),
    ("PWD CR 2", "PWD comfort room 2", MAIN, GROUND, "Comfort room"),
    ("C.R Female (2nd floor)", "Female comfort room, 2nd floor", MAIN, SECOND, "Comfort room"),
    ("Storage 1", "Storage room 1", MAIN, GROUND, "Storage"), ("Storage 2", "Storage room 2", MAIN, GROUND, "Storage"),
    # Yellow Building (from Yellow_Bldfg.xlsx)
    ("Dark Room", "Darkroom", BLDG2, SECOND, "Criminology laboratory"),
    ("Interrogation Room", "Interrogation Room", BLDG2, SECOND, "Criminology laboratory"),
    ("Observation Room", "Observation Room", BLDG2, SECOND, "Criminology laboratory"),
    ("Moot Court", "Moot Court", BLDG2, SECOND, "Moot court"),
    ("DEPTAC", "DEFTAC Room", BLDG2, SECOND, "Room"),
    ("Crime Lab 1", "Crime Laboratory 1", BLDG2, GROUND, "Criminology laboratory"),
    ("Ballistic Room", "Ballistics", BLDG2, GROUND, "Criminology laboratory"),
    ("Com Lab 1", "Computer Laboratory 1", BLDG2, GROUND, "Computer laboratory"),
    ("Com Lab 2", "Computer Laboratory 2", BLDG2, GROUND, "Computer laboratory"),
    ("NSTP Room (Yellow Building)", "NSTP (Facility Management)", BLDG2, GROUND, "Room"),
    ("PWD CR (Yellow Building)", "PWD comfort room", BLDG2, GROUND, "Comfort room"),
    ("Public CR (1st floor, NE)", "Public comfort room, 1st floor (NE)", BLDG2, GROUND, "Comfort room"),
    ("Public CR (1st floor, SE)", "Public comfort room, 1st floor (SE)", BLDG2, GROUND, "Comfort room"),
    ("Public CR (2nd floor)", "Public comfort room, 2nd floor", BLDG2, SECOND, "Comfort room"),
    ("Storage (Yellow 1)", "Storage room, Yellow Building 1", BLDG2, SECOND, "Storage"),
    ("Storage (Yellow 2)", "Storage room, Yellow Building 2", BLDG2, SECOND, "Storage"),
]


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower().strip()


def _find_employee(db: Session, last: str, first: str) -> Employee | None:
    last_n, first_n = _plain(last), _plain(first)
    for e in db.scalars(select(Employee)):
        if _plain(e.last_name) == last_n or (_plain(e.last_name).startswith(last_n + " ")):
            if (_plain(e.first_name).startswith(first_n) or first_n in _plain(e.first_name)
                    or first_n in _plain(e.last_name)):          # a roster line with no comma keeps the whole name in last_name
                return e
    return None


def apply(db: Session) -> dict:
    """Returns counts of what changed. Commits nothing; the caller commits."""
    out = {"positions": 0, "people_added": 0, "assigned": 0, "offices": 0, "rooms": 0, "rooms_moved": 0, "names_fixed": 0}

    for model in (Office, Room):                       # new building names and floor wording
        for row in db.scalars(select(model)):
            if row.building in OLD_BUILDINGS:
                row.building = OLD_BUILDINGS[row.building]
            if row.floor in OLD_FLOORS:
                row.floor = OLD_FLOORS[row.floor]
    db.flush()

    pos = {}
    for title, desc in POSITIONS.items():
        p = db.scalar(select(Position).where(Position.name == title))
        if not p:
            p = Position(name=title, description=desc)
            db.add(p)
            db.flush()
            out["positions"] += 1
        pos[title] = p

    offices = {}
    for name, building, floor, shares, about, room_name in OFFICES:
        o = db.scalar(select(Office).where(Office.name == name))
        if not o:
            o = Office(name=name, description=about or name)
            db.add(o)
            db.flush()
            out["offices"] += 1
        if not o.building:
            o.building = building
        if floor and not o.floor:
            o.floor = floor
        elif name in OFFICE_FLOOR_FIXES and o.floor == OFFICE_FLOOR_FIXES[name] and floor != o.floor:
            o.floor = floor                           # the Yellow Building sheet puts it on the 1st floor
        if room_name and not o.room_number:
            o.room_number = room_name                 # the room's name on the plan, e.g. "Registrar Office & Admission Office"
        if o.description and "ADD VERIFIED LOCATION, " in o.description:       # the location is now known
            o.description = o.description.replace("ADD VERIFIED LOCATION, ", "ADD VERIFIED ")
        if shares and "shares a room" not in (o.description or "").lower():
            o.description = ((o.description or "").rstrip() + f" It shares a room with {shares}.").strip()
        offices[name] = o
    db.flush()

    for first, middle, last, note in NEW_PEOPLE:
        if not _find_employee(db, last, first.split()[0]):
            db.add(Employee(first_name=first, last_name=last, description=note, status="active"))
            out["people_added"] += 1
    db.flush()

    groups = {"Faculty", "Administrative Personnel"}
    for last, first, title, office_name in ASSIGNMENTS:
        e = _find_employee(db, last, first)
        if not e:
            continue
        if last == "Benedicto" and e.first_name.startswith("[ADMIN"):          # the roster has no comma in this name
            e.first_name, e.middle_name = "Reymundo", "Rabino"
            if "Rabino" in e.last_name:
                e.last_name = "Benedicto"
            out["names_fixed"] += 1
        if e.position_id is None or (e.position and (e.position.name in groups or e.position.name in OLD_CAMPUS_TITLES)):
            e.position_id = pos[title].id
            out["assigned"] += 1
        if office_name and e.office_id is None and office_name in offices:
            e.office_id = offices[office_name].id

    db.flush()
    for old in OLD_CAMPUS_TITLES:                      # drop a replaced title nobody holds any more
        p_old = db.scalar(select(Position).where(Position.name == old))
        if p_old and not db.scalar(select(Employee).where(Employee.position_id == p_old.id)):
            db.delete(p_old)

    for number, name, building, floor, rtype in ROOMS:
        r = db.scalar(select(Room).where(Room.room_number == number, Room.building == building))
        if not r:
            db.add(Room(room_number=number, room_name=name, building=building, floor=floor, room_type=rtype))
            out["rooms"] += 1
        elif number in MOVED and r.floor == MOVED[number] and floor != r.floor:
            r.floor = floor
            out["rooms_moved"] += 1
        elif not r.floor and floor:
            r.floor = floor
    for old_number, old_building in OLD_ROOMS:
        r = db.scalar(select(Room).where(Room.room_number == old_number, Room.building == old_building))
        if r:
            db.delete(r)
    return out
