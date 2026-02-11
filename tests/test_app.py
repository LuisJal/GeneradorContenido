"""Tests for FastAPI application: health endpoint and basic responses."""
from starlette.testclient import TestClient

from app.main import app


def test_health_endpoint():
    """GET /api/health should return 200 with status ok."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_dashboard_home():
    """GET / should return 200 with HTML content."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "GeneradorContenido" in response.text


def test_static_css_served():
    """Static CSS file should be accessible."""
    client = TestClient(app)
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
