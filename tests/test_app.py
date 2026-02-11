"""Tests for FastAPI application: health endpoint and basic responses."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def client():
    """Synchronous test client for FastAPI."""
    from starlette.testclient import TestClient
    return TestClient(app)


def test_health_endpoint(client):
    """GET /api/health should return 200 with status ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_dashboard_home(client):
    """GET / should return 200 with HTML content."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "GeneradorContenido" in response.text


def test_static_css_served(client):
    """Static CSS file should be accessible."""
    response = client.get("/static/css/style.css")
    assert response.status_code == 200


def test_404_returns_html(client):
    """Non-existent routes should return 404."""
    response = client.get("/nonexistent-page-xyz")
    assert response.status_code == 404
