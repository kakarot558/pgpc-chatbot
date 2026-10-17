"""CRUD tests for every data module (employees, offices, rooms, facilities, handbook, ...)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import hash_password
from app.database.database import Base, get_db
from app.main import app
from app.models import User


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)

    def override():
        with Session_() as s:
            yield s

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    with Session_() as s:
        s.add(User(username="boss", email="boss@x.com", password_hash=hash_password("AdminPass1"), role="admin"))
        s.add(User(username="stud", email="stud@x.com", password_hash=hash_password("StudPass12"), role="user"))
        s.commit()
    c.admin = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": "boss", "password": "AdminPass1"}).json()["access_token"]}
    c.user = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": "stud", "password": "StudPass12"}).json()["access_token"]}
    yield c
    app.dependency_overrides.clear()


# One valid sample record and one field to edit, per module.
SAMPLES = {
    "positions": ({"name": "Test Position"}, "description", "edited"),
    "offices": ({"name": "Test Office", "building": "Main"}, "floor", "2"),
    "facilities": ({"name": "Test Facility", "location": "Main"}, "operating_hours", "8-5"),
    "rooms": ({"room_number": "T-101", "building": "Main"}, "room_type", "Lecture"),
    "employees": ({"first_name": "Test", "last_name": "Person"}, "description", "edited"),
    "handbook": ({"title": "Test rule", "content": "This is a test handbook section."}, "category", "Test"),
    "history": ({"title": "Test event", "year": "2000", "content": "Test history content."}, "source", "Test"),
    "faqs": ({"question": "Test question?", "answer": "Test answer."}, "category", "Test"),
    "library": ({"title": "Test Book", "isbn": "123"}, "author", "Tester"),
}


@pytest.mark.parametrize("path", SAMPLES)
def test_full_crud_cycle(client, path):
    body, field, new_value = SAMPLES[path]
    created = client.post(f"/api/v1/admin/{path}", json=body, headers=client.admin)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    # public read works without logging in
    assert client.get(f"/api/v1/{path}").json()["total"] == 1
    assert client.get(f"/api/v1/{path}/{rid}").status_code == 200

    edited = client.put(f"/api/v1/admin/{path}/{rid}", json={field: new_value}, headers=client.admin)
    assert edited.status_code == 200 and edited.json()[field] == new_value

    assert client.delete(f"/api/v1/admin/{path}/{rid}", headers=client.admin).status_code == 200
    assert client.get(f"/api/v1/{path}/{rid}").status_code == 404


@pytest.mark.parametrize("path", SAMPLES)
def test_writes_are_admin_only(client, path):
    body = SAMPLES[path][0]
    assert client.post(f"/api/v1/admin/{path}", json=body).status_code == 401
    assert client.post(f"/api/v1/admin/{path}", json=body, headers=client.user).status_code == 403
    assert client.put(f"/api/v1/admin/{path}/1", json={}, headers=client.user).status_code == 403
    assert client.delete(f"/api/v1/admin/{path}/1", headers=client.user).status_code == 403


@pytest.mark.parametrize("path", ["positions", "offices", "facilities", "rooms", "employees", "faqs", "library"])
def test_duplicates_rejected_case_insensitively(client, path):
    body = SAMPLES[path][0]
    assert client.post(f"/api/v1/admin/{path}", json=body, headers=client.admin).status_code == 201
    shouted = {k: (v.upper() if isinstance(v, str) else v) for k, v in body.items()}
    r = client.post(f"/api/v1/admin/{path}", json=shouted, headers=client.admin)
    assert r.status_code == 409, r.text


def test_same_room_number_allowed_in_other_building(client):
    client.post("/api/v1/admin/rooms", json={"room_number": "101", "building": "A"}, headers=client.admin)
    assert client.post("/api/v1/admin/rooms", json={"room_number": "101", "building": "B"}, headers=client.admin).status_code == 201


def test_required_fields_and_invalid_input(client):
    a = client.admin
    assert client.post("/api/v1/admin/offices", json={}, headers=a).status_code == 422
    assert client.post("/api/v1/admin/offices", json={"name": "   "}, headers=a).status_code == 422
    assert client.post("/api/v1/admin/offices", json={"name": "X", "email": "not-an-email"}, headers=a).status_code == 422
    assert client.post("/api/v1/admin/employees", json={"first_name": "A", "last_name": "B", "email": "bad"}, headers=a).status_code == 422
    # empty handbook section
    assert client.post("/api/v1/admin/handbook", json={"title": "T", "content": ""}, headers=a).status_code == 422
    assert client.post("/api/v1/admin/handbook", json={"title": "T", "content": "short"}, headers=a).status_code == 422


def test_blank_optional_becomes_null_and_required_cannot_be_blanked(client):
    r = client.post("/api/v1/admin/offices", json={"name": "O", "email": "", "floor": " "}, headers=client.admin)
    assert r.status_code == 201 and r.json()["email"] is None and r.json()["floor"] is None
    rid = r.json()["id"]
    assert client.put(f"/api/v1/admin/offices/{rid}", json={"name": None}, headers=client.admin).status_code == 422
    assert client.put(f"/api/v1/admin/offices/{rid}", json={"name": " "}, headers=client.admin).status_code == 422


def test_employee_links_and_in_use_protection(client):
    a = client.admin
    pos = client.post("/api/v1/admin/positions", json={"name": "Registrar"}, headers=a).json()["id"]
    off = client.post("/api/v1/admin/offices", json={"name": "Registrar's Office"}, headers=a).json()["id"]
    bad = client.post("/api/v1/admin/employees", json={"first_name": "A", "last_name": "B", "position_id": 999}, headers=a)
    assert bad.status_code == 422
    emp = client.post("/api/v1/admin/employees", json={"first_name": "A", "last_name": "B", "position_id": pos, "office_id": off}, headers=a)
    assert emp.status_code == 201
    assert emp.json()["position"]["name"] == "Registrar" and emp.json()["office"]["name"] == "Registrar's Office"
    assert client.delete(f"/api/v1/admin/positions/{pos}", headers=a).status_code == 409
    assert client.delete(f"/api/v1/admin/offices/{off}", headers=a).status_code == 409
    client.delete(f"/api/v1/admin/employees/{emp.json()['id']}", headers=a)
    assert client.delete(f"/api/v1/admin/positions/{pos}", headers=a).status_code == 200


def test_facility_with_rooms_cannot_be_deleted(client):
    a = client.admin
    fid = client.post("/api/v1/admin/facilities", json={"name": "Library"}, headers=a).json()["id"]
    client.post("/api/v1/admin/rooms", json={"room_number": "L1", "facility_id": fid}, headers=a)
    assert client.delete(f"/api/v1/admin/facilities/{fid}", headers=a).status_code == 409
    assert client.post("/api/v1/admin/rooms", json={"room_number": "L2", "facility_id": 999}, headers=a).status_code == 422


def test_inactive_faq_hidden_from_public_but_visible_to_admin(client):
    a = client.admin
    r = client.post("/api/v1/admin/faqs", json={"question": "Draft?", "answer": "Not ready", "is_active": False}, headers=a)
    fid = r.json()["id"]
    assert client.get("/api/v1/faqs").json()["total"] == 0
    assert client.get(f"/api/v1/faqs/{fid}").status_code == 404
    assert client.get("/api/v1/admin/faqs", headers=a).json()["total"] == 1
    assert client.get("/api/v1/admin/faqs").status_code == 401
    client.put(f"/api/v1/admin/faqs/{fid}", json={"is_active": True}, headers=a)
    assert client.get("/api/v1/faqs").json()["total"] == 1


def test_search_and_paging_limits(client):
    a = client.admin
    for n in ("Registrar's Office", "Library", "Clinic"):
        client.post("/api/v1/admin/offices", json={"name": n}, headers=a)
    found = client.get("/api/v1/offices", params={"q": "registrar"}).json()
    assert found["total"] == 1 and found["items"][0]["name"] == "Registrar's Office"
    assert client.get("/api/v1/offices", params={"limit": 2}).json()["items"].__len__() == 2
    assert client.get("/api/v1/offices", params={"limit": 1000}).status_code == 422
    assert client.get("/api/v1/offices", params={"skip": -1}).status_code == 422


def test_unknown_id_is_404(client):
    assert client.get("/api/v1/employees/999").status_code == 404
    assert client.put("/api/v1/admin/employees/999", json={"first_name": "X"}, headers=client.admin).status_code == 404
