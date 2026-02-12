"""Tests for /settings page routes."""
from __future__ import annotations

from unittest.mock import patch

from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)

# Complete settings dict matching all SETTING_DEFINITIONS keys
_EMPTY_SETTINGS = {
    "gemini_api_key": "",
    "google_cloud_project": "",
    "google_application_credentials": "",
    "kling_access_key": "",
    "kling_secret_key": "",
    "kling_api_key": "",
    "aiml_api_key": "",
    "elevenlabs_api_key": "",
    "hedra_api_key": "",
    "telegram_bot_token": "",
    "football_data_api_key": "",
    "gnews_api_key": "",
}


def test_settings_page_loads():
    """GET /settings returns 200 with form fields."""
    with patch("app.routers.dashboard.get_all_settings", return_value=_EMPTY_SETTINGS):
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Configuracion" in resp.text
    assert "gemini_api_key" in resp.text


def test_settings_page_shows_configured():
    """GET /settings shows masked values for configured keys."""
    settings = {**_EMPTY_SETTINGS, "gemini_api_key": "***configurado***", "google_cloud_project": "my-project"}
    with patch("app.routers.dashboard.get_all_settings", return_value=settings):
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "***configurado***" in resp.text
    assert "my-project" in resp.text


def test_settings_save():
    """POST /settings saves values and shows success message."""
    with patch("app.routers.dashboard.save_setting") as mock_save, \
         patch("app.routers.dashboard.get_all_settings", return_value={
             **_EMPTY_SETTINGS,
             "gemini_api_key": "***configurado***",
             "google_cloud_project": "new-project",
         }):
        resp = client.post("/settings", data={
            "gemini_api_key": "AIza-new-key",
            "google_cloud_project": "new-project",
        })
    assert resp.status_code == 200
    assert "Configuracion guardada" in resp.text
    # save_setting should be called for each non-empty value
    assert mock_save.call_count == 2


def test_settings_save_skips_empty():
    """POST /settings does not call save_setting for empty fields."""
    with patch("app.routers.dashboard.save_setting") as mock_save, \
         patch("app.routers.dashboard.get_all_settings", return_value=_EMPTY_SETTINGS):
        resp = client.post("/settings", data={
            "gemini_api_key": "",
            "google_cloud_project": "",
        })
    assert resp.status_code == 200
    mock_save.assert_not_called()


def test_navbar_has_settings_link():
    """The navbar should include a link to /settings."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/settings"' in resp.text
    assert "Configuracion" in resp.text


def test_settings_grouped_sections():
    """Settings page should have grouped sections with status indicators."""
    with patch("app.routers.dashboard.get_all_settings", return_value={
        **_EMPTY_SETTINGS,
        "gemini_api_key": "***configurado***",
    }):
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Esencial" in resp.text
    assert "Generacion de Video" in resp.text
    assert "Personaje IA" in resp.text
    assert "Fuentes de Noticias" in resp.text
    assert "Opcional" in resp.text
    # Gemini is configured → "Configurado" badge should appear
    assert "Configurado" in resp.text
