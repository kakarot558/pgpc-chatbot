"""Phase 11 tests: document upload, text extraction, chunks, archive/replace and search (in-memory SQLite)."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.database.database import Base, get_db
from app.main import app
from app.models import Document, KnowledgeChunk, User
from app.services import document_service as svc
from app.services import retrieval as rv

POLICY = (
    "PGPC Library Borrowing Policy\n\n"
    "Students may borrow up to three books at a time using their school identification card. "
    "Borrowed books must be returned within seven days. A fine of five pesos per day is charged "
    "for every overdue book. Reference books and theses cannot be taken out of the library.\n\n"
    "Lost books must be replaced with the same title or paid for at the current price. "
    "The librarian on duty will issue an official clearance after all books have been returned."
)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    rv.clear_index_cache()
    yield sessionmaker(bind=engine)
    rv.clear_index_cache()


@pytest.fixture()
def client(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "STORAGE_DIR", tmp_path)          # never write into the real data folder

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    with session_factory() as s:
        s.add(User(username="boss", email="boss@x.com", password_hash=hash_password("AdminPass1"), role="admin"))
        s.add(User(username="stud", email="stud@x.com", password_hash=hash_password("StudPass12"), role="user"))
        s.commit()
    tok = lambda n, p: {"Authorization": "Bearer " + c.post("/api/v1/auth/login", data={"username": n, "password": p}).json()["access_token"]}
    c.admin, c.user = tok("boss", "AdminPass1"), tok("stud", "StudPass12")
    yield c
    app.dependency_overrides.clear()


def upload(client, name="borrowing.txt", data=POLICY.encode(), **form):
    return client.post("/api/v1/admin/documents", files={"file": (name, data)}, data=form, headers=client.admin)


# ------------------------------------------------------------------ access
def test_documents_are_admin_only(client):
    assert client.get("/api/v1/admin/documents").status_code == 401
    assert client.get("/api/v1/admin/documents", headers=client.user).status_code == 403
    assert client.post("/api/v1/admin/documents", files={"file": ("a.txt", b"hello world")}).status_code == 401


# ------------------------------------------------------------------ upload and extraction
def test_text_upload_creates_document_and_chunks(client, session_factory):
    res = upload(client, title="Library Borrowing Policy", source="PGPC Library Manual", category="Library")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "active" and body["file_type"] == "txt" and body["chunks"] >= 1
    chunks = client.get(f"/api/v1/admin/documents/{body['id']}/chunks", headers=client.admin).json()
    assert chunks["items"][0]["category"] == "Library" and "borrow" in chunks["items"][0]["content"].lower()
    assert chunks["items"][0]["keywords"]                      # TF-IDF / frequency keywords were saved
    assert (svc.STORAGE_DIR / f"{body['id']}.txt").exists()
    assert client.get(f"/api/v1/admin/documents/{body['id']}/file", headers=client.admin).content == POLICY.encode()


def test_title_defaults_to_the_file_name(client):
    assert upload(client, name="Dress Code 2026.txt", data=b"Students must wear the prescribed uniform inside the campus.").json()["title"] == "Dress Code 2026"


@pytest.mark.parametrize("name,data,code", [
    ("virus.exe", b"MZ....", 415),
    ("notes.txt", b"", 422),
    ("fake.pdf", b"this is not a pdf", 422),
    ("fake.docx", b"this is not a zip", 422),
    ("binary.txt", b"abc\x00\x01\x02" * 100, 422),
    ("blank.txt", b"   \n\n  \t ", 422),
])
def test_bad_files_are_rejected_and_nothing_is_saved(client, session_factory, name, data, code):
    assert upload(client, name=name, data=data).status_code == code
    with session_factory() as s:
        assert s.scalars(select(Document)).all() == [] and s.scalars(select(KnowledgeChunk)).all() == []
    assert list(svc.STORAGE_DIR.iterdir()) == []


def test_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    assert upload(client, data=b"word " * 300_000).status_code == 413


def test_folder_tricks_in_the_file_name_are_removed():
    assert svc.safe_name("../../etc/passwd.txt") == "passwd.txt"
    assert svc.safe_name("C:\\Users\\me\\a b.txt") == "a b.txt"
    assert svc.safe_name(None) == "document"


def test_docx_upload(client):
    docx = pytest.importorskip("docx")
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("Enrollment requirements for new students include the report card and a birth certificate.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Form 138", "Original copy"
    d.save(buf)
    res = upload(client, name="requirements.docx", data=buf.getvalue())
    assert res.status_code == 201, res.text
    text = client.get(f"/api/v1/admin/documents/{res.json()['id']}/chunks", headers=client.admin).json()["items"][0]["content"]
    assert "report card" in text and "Form 138 | Original copy" in text


def test_docx_that_is_only_a_zip_is_rejected(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    assert upload(client, name="x.docx", data=buf.getvalue()).status_code == 422


# ------------------------------------------------------------------ the chatbot uses the document
def ask(client, q):
    return client.get("/api/v1/answer", params={"q": q}).json()


def test_uploaded_document_answers_questions_with_a_source(client):
    upload(client, title="Library Borrowing Policy", source="PGPC Library Manual")
    body = ask(client, "how many books can a student borrow from the library")
    assert body["found"] and body["sources"][0]["type"] == "document"
    assert "three books" in body["answer"] and "PGPC Library Manual" in body["answer"]


def test_archived_document_is_never_used(client):
    doc = upload(client, title="Library Borrowing Policy").json()
    assert ask(client, "what is the fine for an overdue book")["found"]
    assert client.post(f"/api/v1/admin/documents/{doc['id']}/archive", headers=client.admin).json()["status"] == "archived"
    assert not ask(client, "what is the fine for an overdue book")["found"]
    assert client.post(f"/api/v1/admin/documents/{doc['id']}/restore", headers=client.admin).json()["status"] == "active"
    assert ask(client, "what is the fine for an overdue book")["found"]


def test_replacing_a_document_archives_the_old_version(client):
    old = upload(client, title="Library Borrowing Policy").json()
    new_text = POLICY.replace("five pesos", "ten pesos").encode()
    res = upload(client, data=new_text, title="Library Borrowing Policy", replaces_id=str(old["id"]))
    assert res.status_code == 201, res.text
    assert client.get(f"/api/v1/admin/documents/{old['id']}", headers=client.admin).json()["status"] == "archived"
    answer = ask(client, "what is the fine for an overdue book")["answer"]
    assert "ten pesos" in answer and "five pesos" not in answer


def test_duplicate_active_title_is_refused(client):
    assert upload(client, title="Library Borrowing Policy").status_code == 201
    assert upload(client, title="library borrowing policy").status_code == 409


# ------------------------------------------------------------------ management
def test_edit_metadata_updates_chunk_source(client):
    doc = upload(client, title="Old title").json()
    res = client.put(f"/api/v1/admin/documents/{doc['id']}", json={"title": "New title", "source": "Handbook 2026"},
                     headers=client.admin)
    assert res.status_code == 200 and res.json()["title"] == "New title"
    chunk = client.get(f"/api/v1/admin/documents/{doc['id']}/chunks", headers=client.admin).json()["items"][0]
    assert chunk["id"]
    assert client.put(f"/api/v1/admin/documents/{doc['id']}", json={"title": "  "}, headers=client.admin).status_code == 422


def test_delete_needs_archive_first_and_removes_everything(client, session_factory):
    doc = upload(client).json()
    url = f"/api/v1/admin/documents/{doc['id']}"
    assert client.delete(url, headers=client.admin).status_code == 409
    client.post(url + "/archive", headers=client.admin)
    assert client.delete(url, headers=client.admin).status_code == 200
    with session_factory() as s:
        assert s.scalars(select(Document)).all() == [] and s.scalars(select(KnowledgeChunk)).all() == []
    assert list(svc.STORAGE_DIR.iterdir()) == []
    assert client.get(url, headers=client.admin).status_code == 404


def test_reprocess_rebuilds_chunks(client, session_factory):
    doc = upload(client).json()
    with session_factory() as s:
        s.query(KnowledgeChunk).delete()
        s.commit()
    assert client.get(f"/api/v1/admin/documents/{doc['id']}", headers=client.admin).json()["chunks"] == 0
    assert client.post(f"/api/v1/admin/documents/{doc['id']}/reprocess", headers=client.admin).json()["chunks"] >= 1


def test_list_filters(client):
    a = upload(client, title="Alpha policy").json()
    upload(client, name="b.txt", data=POLICY.encode(), title="Beta policy")
    client.post(f"/api/v1/admin/documents/{a['id']}/archive", headers=client.admin)
    assert client.get("/api/v1/admin/documents", params={"status": "archived"}, headers=client.admin).json()["total"] == 1
    assert client.get("/api/v1/admin/documents", params={"q": "beta"}, headers=client.admin).json()["total"] == 1
    assert client.get("/api/v1/admin/documents", params={"status": "bogus"}, headers=client.admin).status_code == 422
