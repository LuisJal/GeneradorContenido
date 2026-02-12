"""Tests for app.config - verify Settings loads correctly with defaults and overrides."""
import os
from pathlib import Path


def test_settings_loads_with_defaults():
    """Settings should instantiate with sensible defaults even without .env."""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        encryption_key="test-key",
        app_secret_key="test-secret",
    )
    assert s.app_env == "development"
    assert s.app_base_url == "http://127.0.0.1:8000"
    assert s.log_level == "INFO"
    assert s.is_development is True


def test_settings_database_url_default():
    """Default database URL should point to a local SQLite file."""
    from app.config import Settings

    s = Settings(_env_file=None, encryption_key="x", app_secret_key="x")
    assert "sqlite" in s.database_url
    assert "generador.db" in s.database_url


def test_settings_storage_dirs():
    """Storage directory properties should return Path objects under project root."""
    from app.config import Settings

    s = Settings(_env_file=None, encryption_key="x", app_secret_key="x")
    assert isinstance(s.videos_dir, Path)
    assert isinstance(s.thumbnails_dir, Path)
    assert "storage/videos" in str(s.videos_dir)
    assert "storage/thumbnails" in str(s.thumbnails_dir)


def test_settings_from_env_vars(monkeypatch):
    """Settings should read from environment variables."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENCRYPTION_KEY", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "test")

    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.app_env == "production"
    assert s.is_development is False
    assert s.log_level == "DEBUG"
