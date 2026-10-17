from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.database.database import Base, get_db
from app.main import app
from app.models import User

GOOD = {"username": "Student1", "email": "Student1@Example.com", "password": "Passw0rd123"}


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
    c.session_factory = Session_
    yield c
    app.dependency_overrides.clear()


def login(client, username, password):
    return client.post("/api/v1/auth/login", data={"username": username, "password": password})


def make_admin(client, username="boss", password="AdminPass1"):
    with client.session_factory() as s:
        s.add(User(username=username, email=f"{username}@x.com", password_hash=hash_password(password), role="admin"))
        s.commit()
    return login(client, username, password).json()["access_token"]


def test_register_and_login(client):
    r = client.post("/api/v1/auth/register", json=GOOD)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "student1" and body["role"] == "user"
    assert "password_hash" not in body and "password" not in body
    assert login(client, "student1", GOOD["password"]).status_code == 200
    assert login(client, "STUDENT1@example.com", GOOD["password"]).status_code == 200  # email, any case


def test_password_is_stored_hashed(client):
    client.post("/api/v1/auth/register", json=GOOD)
    with client.session_factory() as s:
        stored = s.scalar(select(User)).password_hash
    assert stored != GOOD["password"] and stored.startswith("$2")


def test_cannot_register_as_admin(client):
    client.post("/api/v1/auth/register", json={**GOOD, "role": "admin"})
    with client.session_factory() as s:
        assert s.scalar(select(User)).role == "user"


def test_duplicate_and_weak_password_rejected(client):
    client.post("/api/v1/auth/register", json=GOOD)
    assert client.post("/api/v1/auth/register", json=GOOD).status_code == 409
    assert client.post("/api/v1/auth/register", json={**GOOD, "username": "b", "password": "short1"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={**GOOD, "username": "c", "password": "onlyletters"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={**GOOD, "username": "d", "email": "bad"}).status_code == 422


def test_wrong_password_and_unknown_user_same_message(client):
    client.post("/api/v1/auth/register", json=GOOD)
    a = login(client, "student1", "WrongPass1")
    b = login(client, "nobody", "WrongPass1")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_me_requires_valid_token(client):
    client.post("/api/v1/auth/register", json=GOOD)
    token = login(client, "student1", GOOD["password"]).json()["access_token"]
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    ok = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and ok.json()["username"] == "student1"


def test_expired_and_tampered_tokens_rejected(client):
    client.post("/api/v1/auth/register", json=GOOD)
    key = get_settings().secret_key
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    expired = jwt.encode({"sub": "1", "role": "user", "exp": past}, key, algorithm="HS256")
    forged = jwt.encode({"sub": "1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "wrong-key-wrong-key-wrong-key-wrong", algorithm="HS256")
    for t in (expired, forged):
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_admin_routes_are_role_protected(client):
    client.post("/api/v1/auth/register", json=GOOD)
    user_token = login(client, "student1", GOOD["password"]).json()["access_token"]
    admin_token = make_admin(client)
    assert client.get("/api/v1/admin/ping").status_code == 401
    assert client.get("/api/v1/admin/ping", headers={"Authorization": f"Bearer {user_token}"}).status_code == 403
    assert client.get("/api/v1/admin/ping", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200


def test_disabled_account_cannot_login_or_use_old_token(client):
    client.post("/api/v1/auth/register", json=GOOD)
    token = login(client, "student1", GOOD["password"]).json()["access_token"]
    with client.session_factory() as s:
        u = s.scalar(select(User)); u.is_active = False; s.commit()
    assert login(client, "student1", GOOD["password"]).status_code == 403
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
