"""Tests for database engine and SQLAlchemy models.

Verify that:
- All tables can be created from models
- Bot model works with CRUD operations
- ContentItem, SocialCredential, PipelineLog models work
- Relationships between models are correct
- Unique constraints are enforced
"""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, Bot, ContentItem, SocialCredential, PipelineLog


@pytest.fixture
def db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_all_tables_created():
    """All 4 tables should be created from models."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = inspect(engine).get_table_names()
    assert "bots" in tables
    assert "content_items" in tables
    assert "social_credentials" in tables
    assert "pipeline_logs" in tables


def test_create_bot(db):
    """Should create a bot with all required fields."""
    bot = Bot(
        name="TestBot",
        slug="testbot",
        niche="fitness",
        niche_description="Fitness content",
        content_style="Energetic",
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)

    assert bot.id is not None
    assert bot.name == "TestBot"
    assert bot.slug == "testbot"
    assert bot.is_enabled is False
    assert bot.videos_per_day == 1
    assert bot.video_provider == "veo3"
    assert bot.language == "es"


def test_bot_slug_generation():
    """Bot.generate_slug should create URL-safe slugs."""
    assert Bot.generate_slug("My Fitness Bot") == "my-fitness-bot"
    assert Bot.generate_slug("  Tech & AI  ") == "tech-ai"
    assert Bot.generate_slug("Bot #1 (test)") == "bot-1-test"


def test_bot_unique_name(db):
    """Two bots cannot have the same name."""
    bot1 = Bot(name="UniqueBot", slug="unique-1", niche="tech")
    bot2 = Bot(name="UniqueBot", slug="unique-2", niche="fitness")
    db.add(bot1)
    db.commit()
    db.add(bot2)
    with pytest.raises(Exception):
        db.commit()


def test_create_content_item(db):
    """Should create a content item linked to a bot."""
    bot = Bot(name="ContentBot", slug="content-bot", niche="tech")
    db.add(bot)
    db.commit()

    item = ContentItem(bot_id=bot.id, status="trend_scraping")
    db.add(item)
    db.commit()
    db.refresh(item)

    assert item.id is not None
    assert item.bot_id == bot.id
    assert item.status == "trend_scraping"
    assert item.retry_count == 0


def test_create_social_credential(db):
    """Should create credentials linked to a bot."""
    bot = Bot(name="CredBot", slug="cred-bot", niche="finance")
    db.add(bot)
    db.commit()

    cred = SocialCredential(
        bot_id=bot.id,
        platform="instagram",
        access_token_encrypted="encrypted_token_here",
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)

    assert cred.id is not None
    assert cred.platform == "instagram"
    assert cred.is_active is True


def test_credential_unique_bot_platform(db):
    """A bot cannot have two credentials for the same platform."""
    bot = Bot(name="DupBot", slug="dup-bot", niche="tech")
    db.add(bot)
    db.commit()

    cred1 = SocialCredential(bot_id=bot.id, platform="youtube")
    cred2 = SocialCredential(bot_id=bot.id, platform="youtube")
    db.add(cred1)
    db.commit()
    db.add(cred2)
    with pytest.raises(Exception):
        db.commit()


def test_create_pipeline_log(db):
    """Should create a log entry linked to a bot."""
    bot = Bot(name="LogBot", slug="log-bot", niche="fitness")
    db.add(bot)
    db.commit()

    log = PipelineLog(
        bot_id=bot.id,
        stage="script_generating",
        message="Started script generation",
        level="INFO",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    assert log.id is not None
    assert log.stage == "script_generating"


def test_bot_cascade_delete(db):
    """Deleting a bot should cascade delete related items."""
    bot = Bot(name="CascadeBot", slug="cascade-bot", niche="tech")
    db.add(bot)
    db.commit()

    item = ContentItem(bot_id=bot.id, status="draft")
    cred = SocialCredential(bot_id=bot.id, platform="tiktok")
    log = PipelineLog(bot_id=bot.id, stage="test", message="test")
    db.add_all([item, cred, log])
    db.commit()

    db.delete(bot)
    db.commit()

    assert db.query(ContentItem).count() == 0
    assert db.query(SocialCredential).count() == 0
    assert db.query(PipelineLog).count() == 0


def test_bot_content_relationship(db):
    """Bot.content_items relationship should work."""
    bot = Bot(name="RelBot", slug="rel-bot", niche="fitness")
    db.add(bot)
    db.commit()

    item1 = ContentItem(bot_id=bot.id, status="published")
    item2 = ContentItem(bot_id=bot.id, status="failed")
    db.add_all([item1, item2])
    db.commit()
    db.refresh(bot)

    assert len(bot.content_items) == 2
