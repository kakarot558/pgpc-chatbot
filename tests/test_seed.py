from pathlib import Path

from app.database.seed import (EMPLOYEE_FILE, HANDBOOK_FILE, parse_handbook, parse_name,
                               read_roster, smart_title)


def test_parse_name_with_comma_and_note():
    p = parse_name("ARAGON JR. , LUIS (KUYA GUARD)")
    assert p["last_name"] == "Aragon Jr." and p["first_name"] == "Luis" and p["roster_note"] == "KUYA GUARD"


def test_parse_name_without_comma_is_not_guessed():
    assert parse_name("DE LEON MILGREG")["first_name"] == "[ADMIN: VERIFY NAME]"


def test_roster_has_names_only():
    people = read_roster(EMPLOYEE_FILE)
    assert len(people) == 71
    assert not any(n.strip().upper() in {"XS", "S", "M", "L", "XL", "2XL", "3XL", "5XL"} for _, n in people)


def test_smart_title_keeps_acronyms():
    assert smart_title("OFFICE OF STUDENT AFFAIRS (OSA)") == "Office of Student Affairs (OSA)"


def test_handbook_parses_into_chapters_with_pages():
    recs = parse_handbook(Path(HANDBOOK_FILE).read_text(encoding="utf-8", errors="replace"))
    assert len(recs) > 50
    cats = {r["category"] for r in recs}
    assert any(c and c.startswith("Chapter XIX") for c in cats)
    assert all(len(r["content"]) >= 20 for r in recs)
    assert any(r["source_page"] for r in recs)


# ------------------------------------------------------------ offices and facilities come from the handbook
def test_seeded_offices_and_facilities_are_named_in_the_handbook():
    text = Path(HANDBOOK_FILE).read_text(encoding="utf-8", errors="replace").lower()
    from app.database.seed import FACILITIES, OFFICES
    assert len(OFFICES) == 5 and len(FACILITIES) == 3
    assert len({o["name"].lower() for o in OFFICES}) == len(OFFICES)
    for needle in ("office of the registrar", "cashier", "office of student affairs", "guidance",
                   "sports, arts and culture office", "college clinic", "library", "canteen"):
        assert needle in text, needle
    clinic = next(f for f in FACILITIES if f["name"] == "College Clinic")
    assert clinic["operating_hours"] == "Monday-Friday, 8 AM-5 PM" and "clinic hours" in text
