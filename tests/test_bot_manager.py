"""Tests for bot_manager service: CRUD operations with templates."""
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Bot
from app.schemas.bot import BotCreate, BotUpdate
from app.services import bot_manager


@pytest.fixture(autouse=True)
def mock_encryption_key(monkeypatch):
    """Provide a valid Fernet key for all tests."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.bot_manager.settings.encryption_key", key)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_create_bot_minimal(db):
    """Create a bot with minimum required fields."""
    data = BotCreate(name="TestBot", niche="fitness")
    bot = bot_manager.create_bot(db, data)

    assert bot.id is not None
    assert bot.name == "TestBot"
    assert bot.slug == "testbot"
    assert bot.niche == "fitness"
    assert bot.is_enabled is False
    assert bot.video_provider == "veo3"


def test_create_bot_from_template(db):
    """Create a bot from a fitness template should inherit template values."""
    data = BotCreate(name="FitBot", niche="fitness", template="fitness")
    bot = bot_manager.create_bot(db, data)

    assert bot.niche == "fitness"
    assert "fitness" in bot.niche_description.lower() or "gym" in bot.niche_description.lower()
    assert len(bot.custom_prompts) > 0
    assert bot.script_system_prompt != ""


def test_create_bot_with_api_key(db):
    """API keys should be stored encrypted."""
    data = BotCreate(
        name="KeyBot", niche="tech",
        gemini_api_key="AIzaSyTest12345"
    )
    bot = bot_manager.create_bot(db, data)

    # Encrypted value should NOT be the plaintext
    assert bot.gemini_api_key_encrypted != "AIzaSyTest12345"
    assert bot.gemini_api_key_encrypted is not None


def test_create_bot_duplicate_name(db):
    """Should raise error when creating bot with duplicate name."""
    data = BotCreate(name="UniqueBot", niche="tech")
    bot_manager.create_bot(db, data)

    with pytest.raises(ValueError, match="already exists"):
        bot_manager.create_bot(db, data)


def test_get_bot_by_slug(db):
    """Should retrieve bot by slug."""
    data = BotCreate(name="Slug Bot", niche="finance")
    bot_manager.create_bot(db, data)

    found = bot_manager.get_bot_by_slug(db, "slug-bot")
    assert found is not None
    assert found.name == "Slug Bot"


def test_get_bot_by_slug_not_found(db):
    """Should return None for non-existent slug."""
    found = bot_manager.get_bot_by_slug(db, "nonexistent")
    assert found is None


def test_list_bots(db):
    """Should list all bots."""
    bot_manager.create_bot(db, BotCreate(name="Bot1", niche="a"))
    bot_manager.create_bot(db, BotCreate(name="Bot2", niche="b"))
    bot_manager.create_bot(db, BotCreate(name="Bot3", niche="c"))

    bots = bot_manager.list_bots(db)
    assert len(bots) == 3


def test_update_bot(db):
    """Should update only specified fields."""
    data = BotCreate(name="UpdateMe", niche="tech")
    bot_manager.create_bot(db, data)

    update = BotUpdate(niche_description="Updated description", videos_per_day=3)
    updated = bot_manager.update_bot(db, "updateme", update)

    assert updated.niche_description == "Updated description"
    assert updated.videos_per_day == 3
    assert updated.niche == "tech"  # unchanged


def test_update_bot_not_found(db):
    """Should return None for non-existent bot."""
    update = BotUpdate(niche="new")
    result = bot_manager.update_bot(db, "ghost", update)
    assert result is None


def test_toggle_bot(db):
    """Should toggle enabled state."""
    data = BotCreate(name="ToggleBot", niche="tech")
    bot_manager.create_bot(db, data)

    bot = bot_manager.toggle_bot(db, "togglebot")
    assert bot.is_enabled is True

    bot = bot_manager.toggle_bot(db, "togglebot")
    assert bot.is_enabled is False


def test_delete_bot(db):
    """Should delete bot and return True."""
    data = BotCreate(name="DeleteMe", niche="tech")
    bot_manager.create_bot(db, data)

    result = bot_manager.delete_bot(db, "deleteme")
    assert result is True
    assert bot_manager.get_bot_by_slug(db, "deleteme") is None


def test_delete_bot_not_found(db):
    """Should return False for non-existent bot."""
    result = bot_manager.delete_bot(db, "ghost")
    assert result is False


def test_load_template():
    """Should load a valid template file."""
    template = bot_manager.load_template("fitness")
    assert template["niche"] == "fitness"
    assert "custom_prompts" in template


def test_load_template_not_found():
    """Should raise ValueError for missing template."""
    with pytest.raises(ValueError, match="not found"):
        bot_manager.load_template("nonexistent_template_xyz")
