"""Enrollment procedures, tuition fees and student counts."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import enrollment_data
from app.database.database import Base
from app.database.import_enrollment_counts import import_rows
from app.models import FAQ, EnrollmentCount, TuitionFee
from app.services import enrollment_info as ei


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        enrollment_data.apply(s)
        s.commit()
        yield s


def test_fee_table_matches_the_pgpc_sheet():
    rows = {(r["program"], r["residency"], r["year_level"], r["semester"]): r["amount"] for r in ei.default_fee_rows()}
    assert len(rows) == 4 * 2 * 4 * 2
    assert rows[("BSCS", "Garciano", 1, 1)] == 6600 and rows[("BSCS", "Non-Garciano", 1, 1)] == 8800
    assert rows[("BSCRIM", "Garciano", 2, 1)] == 9000 and rows[("BPA", "Garciano", 4, 2)] == 1800
    assert rows[("BSMA", "Non-Garciano", 3, 1)] == 10800
    for (prog, res, y, s), amount in rows.items():          # the sheet's Non-Garciano is always Garciano x 4/3
        if res == "Garciano":
            assert rows[(prog, "Non-Garciano", y, s)] * 3 == amount * 4


def test_apply_is_idempotent_and_keeps_admin_edits(db):
    assert db.scalar(select(TuitionFee).where(TuitionFee.program == "BSCS", TuitionFee.year_level == 1,
                                              TuitionFee.semester == 1, TuitionFee.residency == "Garciano")).amount == 6600
    fee = db.scalar(select(TuitionFee).where(TuitionFee.program == "BSCS", TuitionFee.year_level == 1,
                                             TuitionFee.semester == 1, TuitionFee.residency == "Garciano"))
    fee.amount = 7000
    faq = db.scalar(select(FAQ).where(FAQ.keywords.like("%incoming%")))
    faq.answer = "Edited by admin."
    db.commit()
    assert enrollment_data.apply(db) == {"fees_added": 0, "procedures_added": 0}
    assert fee.amount == 7000 and faq.answer == "Edited by admin."
    new, sem2 = ei.load_procedures(db)
    assert new == "Edited by admin." and "Program Chair" in sem2


def test_procedure_questions():
    assert ei.procedure_kind("what is the procedure for incoming 1st year") == "new"
    assert ei.procedure_kind("how to enroll as a freshman") == "new"
    assert ei.procedure_kind("enrollment procedure for 2nd sem") == "sem2"
    assert ei.procedure_kind("how do continuing students enroll") == "sem2"
    assert ei.procedure_kind("what is the enrollment procedure") == "general"
    assert ei.procedure_kind("procedure for incoming first year") == "new"
    assert ei.procedure_kind("what is the procedure for dropping 2nd sem") is None
    assert ei.procedure_kind("how to enroll") is None            # the online enrollment link answers this
    assert ei.procedure_kind("what are the requirements for enrollment") is None
    assert ei.procedure_kind("how much is the tuition for enrollment") is None


def test_procedure_text_has_all_steps_and_the_registrar():
    new = ei.procedure_text("new")
    assert "11. Present your Registration Form" in new and "Medical Clearance" in new
    assert "Nicky Jane A. Solis, LPT, College Registrar" in new
    sem2 = ei.procedure_text("sem2")
    assert "9. Present your Registration Form" in sem2 and "Program Chair" in sem2
    assert "https://example.test" in ei.procedure_text("new", link="https://example.test")


def test_fee_answers(db):
    rows = ei.load_fee_rows(db)
    text, found = ei.fee_text(rows, "how much is the tuition for bscs 1st year 1st sem")
    assert found and "₱6,600" in text and "₱8,800" in text and "A.Y. 2025-2026" in text
    text, _ = ei.fee_text(rows, "tuition for bpa 4th year non garciano")
    assert "₱4,800" in text and "₱3,600" not in text
    text, _ = ei.fee_text(rows, "tuition bscrim")
    assert text.count("\n- ") == 8
    text, found = ei.fee_text(rows, "tuition")
    assert found and "Which program" in text
    assert ei.fee_text([], "tuition bscs")[1] is False


def test_which_questions_are_fee_or_count_questions():
    assert ei.is_fee_question("magkano ang tuition sa bscs") or ei.is_fee_question("how much how much is tuition for bscs")
    assert not ei.is_fee_question("how much is the dropping fee")
    assert ei.is_count_question("how many students in bscs") and ei.is_count_question("how many 1st year")
    assert not ei.is_count_question("how many employees") and not ei.is_count_question("how many units can i take")


def test_counts_are_never_invented(db):
    text, found = ei.count_text([], "how many students in bscs")
    assert not found and "Registrar" in text and "BSCS" in text
    text, found = ei.count_text([], "how many students are there")
    assert not found and "nine hundred" in text


def test_counts_from_admin_data(db):
    rows = [
        dict(program="BSCS", year_level=1, students=120, as_of="1st Sem A.Y. 2026-2027", note=None),
        dict(program="BSCS", year_level=2, students=80, as_of="1st Sem A.Y. 2026-2027", note=None),
        dict(program="BPA", year_level=1, students=60, as_of=None, note=None),
    ]
    assert "120 enrolled students" in ei.count_text(rows, "how many bscs 1st year students")[0]
    text, found = ei.count_text(rows, "how many students in bscs")
    assert found and "200" in text and "1st year: 120" in text and "Some year levels" in text
    text, found = ei.count_text(rows, "how many 1st year")
    assert found and "180" in text and "BSCS: 120" in text and "BPA: 60" in text
    assert not ei.count_text(rows, "how many bsma 3rd year students")[1]


def test_import_counts_csv(db):
    out = import_rows(db, [dict(program="bscs", year_level="1", students="1,200", as_of="Sem 1", note=""),
                           dict(program="BPA", year_level="2", students="", as_of="", note=""),
                           dict(program="XYZ", year_level="1", students="5"),
                           dict(program="", year_level="", students="900")])
    db.commit()
    assert out == {"added": 2, "updated": 0, "skipped": 2}
    assert import_rows(db, [dict(program="BSCS", year_level="1", students="1250")])["updated"] == 1
    db.commit()
    assert db.scalar(select(EnrollmentCount.students).where(EnrollmentCount.program == "BSCS")) == 1250


# ------------------------------------------------------------------ admin API
from tests.test_crud import client  # noqa: E402,F401  (the same admin/student test client)


def test_fee_api_admin_only_and_tidies_values(client):
    body = {"program": "bscs", "residency": "non garciano", "year_level": 1, "semester": 1,
            "academic_year": "2026-2027", "amount": 9100}
    assert client.post("/api/v1/admin/tuition-fees", json=body, headers=client.user).status_code == 403
    assert client.post("/api/v1/admin/tuition-fees", json=body).status_code == 401
    made = client.post("/api/v1/admin/tuition-fees", json=body, headers=client.admin)
    assert made.status_code == 201 and made.json()["program"] == "BSCS" and made.json()["residency"] == "Non-Garciano"
    assert client.post("/api/v1/admin/tuition-fees", json=body, headers=client.admin).status_code == 409
    bad = dict(body, program="XYZ")
    assert client.post("/api/v1/admin/tuition-fees", json=bad, headers=client.admin).status_code == 422
    fid = made.json()["id"]
    edited = client.put(f"/api/v1/admin/tuition-fees/{fid}", json={"amount": 9500}, headers=client.admin)
    assert edited.status_code == 200 and edited.json()["amount"] == 9500
    assert client.get("/api/v1/tuition-fees").json()["total"] == 1                 # the public can read fees
    assert client.delete(f"/api/v1/admin/tuition-fees/{fid}", headers=client.admin).status_code in (200, 204)


def test_count_api(client):
    ok = client.post("/api/v1/admin/enrollment-counts", json={"program": "bpa", "year_level": 2, "students": 55,
                     "as_of": "1st Sem A.Y. 2026-2027"}, headers=client.admin)
    assert ok.status_code == 201 and ok.json()["program"] == "BPA"
    assert client.post("/api/v1/admin/enrollment-counts", json={"program": "nope", "students": 5},
                       headers=client.admin).status_code == 422
    assert client.post("/api/v1/admin/enrollment-counts", json={"students": -1}, headers=client.admin).status_code == 422


def test_fee_question_formats():
    from app.services import enrollment_info as ei
    rows = ei.default_fee_rows()
    t = lambda q: ei.fee_text(rows, q)[0]
    assert "₱11,200" in t("magkano ang matrikula ng bsma 1st year para sa hindi taga padre garcia")
    assert "₱8,400" not in t("magkano ang matrikula ng bsma 1st year para sa hindi taga padre garcia").split("Garciano =")[0]
    assert "higher tuition" in t("what is the difference between garciano and non garciano")
    assert "₱1,800" in t("cheapest course")
    assert "BSCS: Garciano ₱6,900" in t("how much is tuition for 2nd year 1st sem")
    assert "A.Y. 2025-2026" not in t("bscs fee 2026-2027 garciano").split("Garciano =")[0]
    assert ei.is_fee_question("what is garciano") and ei.is_fee_question("fees for all courses")
