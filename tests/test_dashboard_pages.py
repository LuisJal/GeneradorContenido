"""Tests for dashboard content, logs, and credentials pages."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.models.log_entry import PipelineLog


@pytest.fixture
def client():
    return TestClient(app)


def _create_bot(db) -> Bot:
    """Insert a minimal bot for page tests."""
    bot = Bot(name="PageTestBot", slug="pagetestbot", niche="tech")
    db.add(bot)
    db.commit()
    return bot


def _get_db():
    """Get test DB session from the override."""
    from app.database import get_db
    db_gen = app.dependency_overrides[get_db]()
    return next(db_gen)


# ------------------------------------------------------------------
# Content list
# ------------------------------------------------------------------


def test_content_list_empty(client):
    db = _get_db()
    bot = _create_bot(db)
    response = client.get(f"/bots/{bot.slug}/content")
    assert response.status_code == 200
    assert "No hay contenido" in response.text


def test_content_list_with_items(client):
    db = _get_db()
    bot = _create_bot(db)

    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.PUBLISHED.value,
        trend_topic="AI tips",
    )
    db.add(item)
    db.commit()

    response = client.get(f"/bots/{bot.slug}/content")
    assert response.status_code == 200
    assert "AI tips" in response.text
    assert "published" in response.text


def test_content_list_404(client):
    response = client.get("/bots/nonexistent/content")
    assert response.status_code == 404


# ------------------------------------------------------------------
# Content detail
# ------------------------------------------------------------------


def test_content_detail(client):
    db = _get_db()
    bot = _create_bot(db)

    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.SCRIPT_READY.value,
        trend_topic="Test topic",
        script='{"hook":"H","body":"B","cta":"C"}',
        video_prompt="A cinematic scene",
    )
    db.add(item)
    db.commit()

    response = client.get(f"/bots/{bot.slug}/content/{item.id}")
    assert response.status_code == 200
    assert "Test topic" in response.text
    assert "script_ready" in response.text
    assert "cinematic" in response.text


def test_content_detail_404(client):
    db = _get_db()
    bot = _create_bot(db)
    response = client.get(f"/bots/{bot.slug}/content/99999")
    assert response.status_code == 404


# ------------------------------------------------------------------
# Logs
# ------------------------------------------------------------------


def test_logs_empty(client):
    db = _get_db()
    bot = _create_bot(db)
    response = client.get(f"/bots/{bot.slug}/logs")
    assert response.status_code == 200
    assert "No hay logs" in response.text


def test_logs_with_entries(client):
    db = _get_db()
    bot = _create_bot(db)

    log = PipelineLog(
        bot_id=bot.id,
        stage="test_stage",
        message="Test log message",
        level="INFO",
    )
    db.add(log)
    db.commit()

    response = client.get(f"/bots/{bot.slug}/logs")
    assert response.status_code == 200
    assert "test_stage" in response.text
    assert "Test log message" in response.text


# ------------------------------------------------------------------
# Credentials
# ------------------------------------------------------------------


def test_credentials_page(client):
    db = _get_db()
    bot = _create_bot(db)
    response = client.get(f"/bots/{bot.slug}/credentials", follow_redirects=False)
    assert response.status_code == 302
    assert f"/bots/{bot.slug}/edit" in response.headers["location"]


def test_add_credential(client):
    db = _get_db()
    bot = _create_bot(db)

    response = client.post(
        f"/bots/{bot.slug}/credentials",
        data={
            "platform": "instagram",
            "access_token": "test-token-123",
            "refresh_token": "",
            "platform_user_id": "ig_user_42",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Verify credential was created
    from app.models.credential import SocialCredential
    cred = db.query(SocialCredential).filter(
        SocialCredential.bot_id == bot.id
    ).first()
    assert cred is not None
    assert cred.platform == "instagram"
    assert cred.platform_user_id == "ig_user_42"


def _add_credential(db, bot):
    """Helper to create a credential for a bot."""
    from app.models.credential import SocialCredential
    from app.utils.encryption import FieldEncryptor
    from app.config import settings

    enc = FieldEncryptor(settings.encryption_key)
    cred = SocialCredential(
        bot_id=bot.id,
        platform="youtube",
        access_token_encrypted=enc.encrypt("yt-token"),
        platform_user_id="yt_user_1",
        is_active=True,
    )
    db.add(cred)
    db.commit()
    return cred


def test_toggle_credential(client):
    """POST toggle should flip is_active and return updated row."""
    db = _get_db()
    bot = _create_bot(db)
    cred = _add_credential(db, bot)
    assert cred.is_active is True

    response = client.post(f"/bots/{bot.slug}/credentials/{cred.id}/toggle")
    assert response.status_code == 200
    assert "Activar" in response.text  # now inactive, button says "Activar"

    db.refresh(cred)
    assert cred.is_active is False


def test_toggle_credential_404(client):
    """POST toggle for nonexistent credential returns 404."""
    db = _get_db()
    bot = _create_bot(db)
    response = client.post(f"/bots/{bot.slug}/credentials/99999/toggle")
    assert response.status_code == 404


def test_delete_credential(client):
    """POST delete should remove the credential."""
    from app.models.credential import SocialCredential

    db = _get_db()
    bot = _create_bot(db)
    cred = _add_credential(db, bot)
    cred_id = cred.id

    response = client.post(f"/bots/{bot.slug}/credentials/{cred_id}/delete")
    assert response.status_code == 200

    deleted = db.query(SocialCredential).filter(SocialCredential.id == cred_id).first()
    assert deleted is None


def test_delete_credential_404(client):
    """POST delete for nonexistent credential returns 404."""
    db = _get_db()
    bot = _create_bot(db)
    response = client.post(f"/bots/{bot.slug}/credentials/99999/delete")
    assert response.status_code == 404


def test_edit_page_shows_credentials(client):
    """GET edit page should show existing credentials."""
    db = _get_db()
    bot = _create_bot(db)
    _add_credential(db, bot)

    response = client.get(f"/bots/{bot.slug}/edit")
    assert response.status_code == 200
    assert "Youtube" in response.text or "youtube" in response.text.lower()
    assert "yt_user_1" in response.text
