"""Tests for dashboard routes: create, detail, edit, toggle, delete bots."""
import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_home(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_bot_create_form(client):
    response = client.get("/bots/new")
    assert response.status_code == 200
    assert "Crear Nuevo Bot" in response.text
    assert "fitness" in response.text.lower()


def test_create_and_view_bot(client):
    """Full flow: create a bot via form, then view its detail page."""
    # Create
    response = client.post("/bots/new", data={
        "name": "TestDashBot",
        "niche": "tech",
        "niche_description": "Tech content",
        "content_style": "Informative",
        "language": "es",
        "videos_per_day": "1",
        "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid",
        "use_trends": "on",
        "video_provider": "veo3",
        "video_duration_seconds": "15",
        "gemini_api_key": "",
        "telegram_chat_id": "",
        "contact_email": "",
        "template": "",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert "/bots/testdashbot" in response.headers["location"]

    # View detail
    detail = client.get("/bots/testdashbot")
    assert detail.status_code == 200
    assert "TestDashBot" in detail.text
    assert "tech" in detail.text


def test_create_bot_from_template(client):
    """Create a bot using the fitness template."""
    response = client.post("/bots/new", data={
        "name": "TemplateFitBot",
        "niche": "fitness",
        "template": "fitness",
        "niche_description": "",
        "content_style": "",
        "language": "es",
        "videos_per_day": "1",
        "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid",
        "use_trends": "on",
        "video_provider": "veo3",
        "video_duration_seconds": "15",
        "gemini_api_key": "",
        "telegram_chat_id": "",
        "contact_email": "",
    }, follow_redirects=False)
    assert response.status_code == 303

    detail = client.get("/bots/templatefitbot")
    assert detail.status_code == 200
    assert "fitness" in detail.text.lower()


def test_bot_edit_form(client):
    """Should show edit form for existing bot."""
    # Create first
    client.post("/bots/new", data={
        "name": "EditFormBot", "niche": "tech",
        "niche_description": "", "content_style": "", "language": "es",
        "videos_per_day": "1", "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid", "use_trends": "on",
        "video_provider": "veo3", "video_duration_seconds": "15",
        "gemini_api_key": "", "telegram_chat_id": "",
        "contact_email": "", "template": "",
    })

    response = client.get("/bots/editformbot/edit")
    assert response.status_code == 200
    assert "Editar" in response.text


def test_bot_toggle(client):
    """Toggle should change bot enabled state."""
    client.post("/bots/new", data={
        "name": "ToggleDashBot", "niche": "tech",
        "niche_description": "", "content_style": "", "language": "es",
        "videos_per_day": "1", "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid", "use_trends": "on",
        "video_provider": "veo3", "video_duration_seconds": "15",
        "gemini_api_key": "", "telegram_chat_id": "",
        "contact_email": "", "template": "",
    })

    response = client.post("/bots/toggledashbot/toggle")
    assert response.status_code == 200
    assert "Activo" in response.text


def test_bot_delete(client):
    """Delete should redirect to home."""
    client.post("/bots/new", data={
        "name": "DeleteDashBot", "niche": "tech",
        "niche_description": "", "content_style": "", "language": "es",
        "videos_per_day": "1", "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid", "use_trends": "on",
        "video_provider": "veo3", "video_duration_seconds": "15",
        "gemini_api_key": "", "telegram_chat_id": "",
        "contact_email": "", "template": "",
    })

    response = client.post("/bots/deletedashbot/delete", follow_redirects=False)
    assert response.status_code == 303

    detail = client.get("/bots/deletedashbot")
    assert detail.status_code == 404


def test_bot_detail_404(client):
    """Non-existent bot should return 404."""
    response = client.get("/bots/nonexistent-bot-xyz")
    assert response.status_code == 404
