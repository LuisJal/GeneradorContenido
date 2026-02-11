"""Tests for app.services.settings_manager."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.global_setting import GlobalSetting
from app.services.settings_manager import (
    ENCRYPTED_KEYS,
    SETTING_DEFINITIONS,
    get_all_settings,
    get_setting,
    save_setting,
)
from app.utils.encryption import FieldEncryptor


@pytest.fixture()
def db():
    """In-memory DB session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture()
def fernet_key():
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _patch_encryption_key(fernet_key):
    with patch("app.services.settings_manager._get_encryptor") as mock_enc:
        mock_enc.return_value = FieldEncryptor(fernet_key)
        yield


# ── save + get round-trip ──


def test_save_and_get_plain_setting(db):
    """Plain (non-encrypted) settings are stored and retrieved as-is."""
    save_setting(db, "google_cloud_project", "my-project-123")
    assert get_setting(db, "google_cloud_project") == "my-project-123"


def test_save_and_get_encrypted_setting(db):
    """Encrypted settings are decrypted on retrieval."""
    save_setting(db, "gemini_api_key", "AIza-secret-key")
    # Raw DB value should NOT be plaintext
    row = db.query(GlobalSetting).filter(GlobalSetting.key == "gemini_api_key").first()
    assert row is not None
    assert row.value != "AIza-secret-key"
    assert row.is_encrypted is True
    # But get_setting returns plaintext
    assert get_setting(db, "gemini_api_key") == "AIza-secret-key"


def test_save_updates_existing(db):
    """Saving the same key twice updates the value."""
    save_setting(db, "google_cloud_project", "old-value")
    save_setting(db, "google_cloud_project", "new-value")
    assert get_setting(db, "google_cloud_project") == "new-value"
    count = db.query(GlobalSetting).filter(GlobalSetting.key == "google_cloud_project").count()
    assert count == 1


def test_save_empty_value_is_noop(db):
    """Saving an empty value does nothing."""
    save_setting(db, "google_cloud_project", "")
    row = db.query(GlobalSetting).filter(GlobalSetting.key == "google_cloud_project").first()
    assert row is None


# ── get_setting fallback ──


def test_get_setting_fallback_to_env(db):
    """When no DB row exists, falls back to env settings."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.gemini_api_key = "env-key-123"
        result = get_setting(db, "gemini_api_key")
    assert result == "env-key-123"


def test_get_setting_returns_empty_for_placeholder(db):
    """Env values starting with PEGA-AQUI are treated as unconfigured."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.gemini_api_key = "PEGA-AQUI-tu-clave"
        result = get_setting(db, "gemini_api_key")
    assert result == ""


# ── get_all_settings ──


def test_get_all_settings_masks_encrypted(db):
    """Encrypted settings show masked value in get_all_settings."""
    save_setting(db, "gemini_api_key", "AIza-secret")
    save_setting(db, "google_cloud_project", "my-project")

    with patch("app.config.settings") as mock_settings:
        # No env fallback needed since values are in DB
        mock_settings.google_cloud_project = ""
        mock_settings.gemini_api_key = ""
        mock_settings.kling_api_key = ""
        mock_settings.telegram_bot_token = ""
        mock_settings.google_application_credentials = ""
        result = get_all_settings(db)

    assert result["gemini_api_key"] == "***configurado***"
    assert result["google_cloud_project"] == "my-project"


def test_get_all_settings_env_fallback(db):
    """Settings not in DB fall back to env with appropriate masking."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.gemini_api_key = "env-key"
        mock_settings.google_cloud_project = "env-project"
        mock_settings.kling_api_key = ""
        mock_settings.telegram_bot_token = ""
        mock_settings.google_application_credentials = ""
        result = get_all_settings(db)

    assert result["gemini_api_key"] == "***desde .env***"
    assert result["google_cloud_project"] == "env-project"
    assert result["kling_api_key"] == ""


# ── definitions ──


def test_all_encrypted_keys_have_definitions():
    """Every encrypted key must have a definition."""
    for key in ENCRYPTED_KEYS:
        assert key in SETTING_DEFINITIONS
