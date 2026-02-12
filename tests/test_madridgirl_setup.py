"""Tests for MadridGirl auto-creation, setup status, and custom prompts editor."""
import pytest
from urllib.parse import urlencode
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.main import app, _ensure_default_bots
from app.models import Base
from app.models.bot import Bot
from app.services.bot_manager import get_bot_by_slug


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    """Provide a DB session matching the test override."""
    from tests.conftest import _test_engine as eng
    with Session(eng) as session:
        yield session


# ── Auto-creation tests ──

def test_ensure_default_bots_creates_madridgirl(db):
    """_ensure_default_bots creates the MadridGirl bot from template."""
    assert get_bot_by_slug(db, "madridgirl") is None
    _ensure_default_bots(db)
    bot = get_bot_by_slug(db, "madridgirl")
    assert bot is not None
    assert bot.name == "MadridGirl"
    assert bot.video_provider == "talking_head"
    assert bot.language == "es"
    assert len(bot.custom_prompts) > 0


def test_ensure_default_bots_idempotent(db):
    """Calling _ensure_default_bots twice only creates one bot."""
    _ensure_default_bots(db)
    _ensure_default_bots(db)
    count = db.query(Bot).filter(Bot.slug == "madridgirl").count()
    assert count == 1


def test_madridgirl_has_character_fields(db):
    """MadridGirl bot has character personality from template."""
    _ensure_default_bots(db)
    bot = get_bot_by_slug(db, "madridgirl")
    assert bot.character_personality is not None
    assert len(bot.character_personality) > 10


# ── Setup status tests ──

def test_bot_detail_shows_setup_checklist(client, db):
    """Talking head bot detail page shows the setup status checklist."""
    _ensure_default_bots(db)
    response = client.get("/bots/madridgirl")
    assert response.status_code == 200
    assert "Estado de configuracion" in response.text
    assert "Configuracion pendiente" in response.text
    assert "Gemini API Key" in response.text
    assert "ElevenLabs API Key" in response.text
    assert "Hedra API Key" in response.text


def test_bot_detail_no_checklist_for_non_talking_head(client):
    """Non-talking-head bots should NOT show the setup checklist."""
    client.post("/bots/new", data={
        "name": "VeoBot",
        "niche": "tech",
        "video_provider": "veo3",
        "video_duration_seconds": "8",
        "videos_per_day": "1",
        "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid",
        "language": "es",
    }, follow_redirects=False)
    response = client.get("/bots/veobot")
    assert response.status_code == 200
    assert "Estado de configuracion" not in response.text


def test_run_button_disabled_when_not_ready(client, db):
    """Run button is disabled when setup is incomplete."""
    _ensure_default_bots(db)
    response = client.get("/bots/madridgirl")
    assert 'disabled' in response.text


def test_api_guide_shown_when_not_ready(client, db):
    """API keys guide is shown when setup is incomplete."""
    _ensure_default_bots(db)
    response = client.get("/bots/madridgirl")
    assert "Donde obtener las claves" in response.text
    assert "aistudio.google.com" in response.text
    assert "elevenlabs.io" in response.text
    assert "hedra.com" in response.text


# ── Custom prompts editor tests ──

def test_bot_edit_shows_custom_prompts(client, db):
    """Bot edit page displays existing custom prompts in editor."""
    _ensure_default_bots(db)
    response = client.get("/bots/madridgirl/edit")
    assert response.status_code == 200
    assert "Prompts Personalizados" in response.text
    assert 'name="custom_prompt"' in response.text


def test_custom_prompts_round_trip(client, db):
    """Saving custom prompts via edit form persists them."""
    _ensure_default_bots(db)

    # Edit with new prompts (use url-encoded body for multi-value fields)
    form_data = urlencode([
        ("niche_description", "Test niche"),
        ("content_style", "Test style"),
        ("language", "es"),
        ("videos_per_day", "1"),
        ("schedule_times", "09:00"),
        ("schedule_timezone", "Europe/Madrid"),
        ("video_provider", "talking_head"),
        ("video_duration_seconds", "30"),
        ("custom_prompt", "Primer prompt editado"),
        ("custom_prompt", "Segundo prompt nuevo"),
        ("custom_prompt", "Tercer prompt"),
    ])
    response = client.post(
        "/bots/madridgirl/edit",
        content=form_data,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Verify prompts were saved (expire cached objects first)
    db.expire_all()
    bot = get_bot_by_slug(db, "madridgirl")
    assert len(bot.custom_prompts) == 3
    assert "Primer prompt editado" in bot.custom_prompts
    assert "Segundo prompt nuevo" in bot.custom_prompts


def test_custom_prompts_can_be_cleared(client, db):
    """Submitting edit form with no prompts clears them."""
    _ensure_default_bots(db)

    # Submit with no custom_prompt fields
    response = client.post("/bots/madridgirl/edit", data={
        "niche_description": "Test",
        "content_style": "",
        "language": "es",
        "videos_per_day": "1",
        "schedule_times": "09:00",
        "schedule_timezone": "Europe/Madrid",
        "video_provider": "talking_head",
        "video_duration_seconds": "30",
    }, follow_redirects=False)
    assert response.status_code == 303

    bot = get_bot_by_slug(db, "madridgirl")
    assert bot.custom_prompts == []
