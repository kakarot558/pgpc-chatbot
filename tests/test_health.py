from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint_reports_status():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["api"] == "running"
    assert body["database"] in ("connected", "unavailable")


def test_frontend_is_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "PGPC SmartGuide" in res.text
