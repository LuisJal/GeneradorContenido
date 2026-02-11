"""Tests for /settings page routes."""
from __future__ import annotations

from unittest.mock import patch

from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_settings_page_loads():
    """GET /settings returns 200 with form fields."""
    with patch("app.routers.dashboard.get_all_settings", return_value={
        "gemini_api_key": "",
        "google_cloud_project": "",
        "google_application_credentials": "",
        "kling_api_key": "",
        "telegram_bot_token": "",
    }):
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Configuracion Global" in resp.text
    assert "gemini_api_key" in resp.text


def test_settings_page_shows_configured():
    """GET /settings shows masked values for configured keys."""
    with patch("app.routers.dashboard.get_all_settings", return_value={
        "gemini_api_key": "***configurado***",
        "google_cloud_project": "my-project",
        "google_application_credentials": "",
        "kling_api_key": "",
        "telegram_bot_token": "",
    }):
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "***configurado***" in resp.text
    assert "my-project" in resp.text


def test_settings_save():
    """POST /settings saves values and shows success message."""
    with patch("app.routers.dashboard.save_setting") as mock_save, \
         patch("app.routers.dashboard.get_all_settings", return_value={
             "gemini_api_key": "***configurado***",
             "google_cloud_project": "new-project",
             "google_application_credentials": "",
             "kling_api_key": "",
             "telegram_bot_token": "",
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
         patch("app.routers.dashboard.get_all_settings", return_value={
             "gemini_api_key": "",
             "google_cloud_project": "",
             "google_application_credentials": "",
             "kling_api_key": "",
             "telegram_bot_token": "",
         }):
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
