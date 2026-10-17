"""Phase 10 and 12 checks on the static pages (no browser needed)."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def test_pages_are_served():
    c = TestClient(app)
    for page, marker in (("/", "chatForm"), ("/index.html", "chatForm"), ("/admin.html", "SmartGuide admin"),
                         ("/login.html", "loginForm"), ("/js/chatbot.js", "/api/v1/chat"),
                         ("/js/admin.js", "/admin/documents"), ("/css/admin.css", ".sg-admin")):
        res = c.get(page)
        assert res.status_code == 200 and marker in res.text, page


def test_scripts_only_use_innerhtml_for_fixed_markup():
    """Server text must go through textContent. The only innerHTML allowed is the typing dots (constant string)."""
    for name in ("chatbot.js", "admin.js"):
        uses = re.findall(r"innerHTML\s*=\s*(.+)", (FRONTEND / "js" / name).read_text(encoding="utf-8"))
        assert all(u.strip().startswith('"<span>') for u in uses), (name, uses)


def test_every_api_path_used_by_the_scripts_exists():
    openapi = TestClient(app).get("/openapi.json").json()["paths"]
    for path in ("/api/v1/chat", "/api/v1/chat/history", "/api/v1/chat/session", "/api/v1/admin/chat/logs",
                 "/api/v1/admin/chat/summary", "/api/v1/admin/chat/sessions/{session_id}",
                 "/api/v1/admin/chat/expired-sessions", "/api/v1/admin/documents",
                 "/api/v1/admin/documents/{doc_id}/chunks", "/api/v1/admin/documents/{doc_id}/file",
                 "/api/v1/admin/documents/{doc_id}/reprocess", "/api/v1/admin/faqs"):
        assert path in openapi, path
