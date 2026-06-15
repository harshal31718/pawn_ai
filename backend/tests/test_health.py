from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_has_security_headers():
    response = client.get("/health")
    assert response.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in response.headers
    assert response.headers.get("x-content-type-options") == "nosniff"
