"""Tests for story arc feature -- multi-chapter content generation."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.models import Base
from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.models.log_entry import PipelineLog
from app.services.pipeline_orchestrator import run_story_arc_pipeline


# ------------------------------------------------------------------
# Test database setup
# ------------------------------------------------------------------


@pytest.fixture
def db():
    """Provide a clean in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def arc_bot(db):
    """Insert a bot with story arcs enabled."""
    b = Bot(
        name="ArcTestBot",
        slug="arctestbot",
        niche="anime",
        niche_description="Anime action stories",
        content_style="dramatic",
        language="es",
        video_provider="veo3",
        video_duration_seconds=8,
        custom_prompts=["Historia epica de samurai"],
        use_trends=False,
        story_arc_enabled=True,
        story_arc_chapters=3,
    )
    db.add(b)
    db.commit()
    return b


# ------------------------------------------------------------------
# Schema tests
# ------------------------------------------------------------------


def test_bot_story_arc_defaults(db):
    """Bot should have story arc fields with correct defaults."""
    b = Bot(name="DefaultBot", slug="defaultbot", niche="test")
    db.add(b)
    db.commit()
    db.refresh(b)
    assert b.story_arc_enabled is False
    assert b.story_arc_chapters == 3


def test_content_item_arc_fields(db, arc_bot):
    """ContentItem should accept story arc fields."""
    item = ContentItem(
        bot_id=arc_bot.id,
        story_arc_id="abc123",
        story_arc_chapter=2,
        story_arc_total=3,
        story_arc_premise="A samurai seeks revenge...",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    assert item.story_arc_id == "abc123"
    assert item.story_arc_chapter == 2
    assert item.story_arc_total == 3
    assert "samurai" in item.story_arc_premise


# ------------------------------------------------------------------
# Pipeline: run_story_arc_pipeline
# ------------------------------------------------------------------


def test_run_story_arc_pipeline_creates_3_chapters(db, arc_bot):
    """Story arc pipeline should create 3 content items with shared arc_id."""
    fake_script = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}

    with patch("app.services.pipeline_orchestrator.script_generator") as sg, \
         patch("app.services.pipeline_orchestrator.video_generator") as vg:

        sg.generate_story_arc_premise = AsyncMock(return_value="A samurai premise...")
        sg.generate_content_script = AsyncMock(return_value=fake_script)
        sg.generate_video_prompt = AsyncMock(return_value="cinematic prompt")
        vg.submit_video_generation = AsyncMock(return_value="task-arc-1")

        items = asyncio.get_event_loop().run_until_complete(
            run_story_arc_pipeline(arc_bot, db)
        )

    assert len(items) == 3

    # All items share the same arc_id
    arc_ids = {item.story_arc_id for item in items}
    assert len(arc_ids) == 1
    assert None not in arc_ids

    # Chapter numbers are 1, 2, 3
    chapters = [item.story_arc_chapter for item in items]
    assert chapters == [1, 2, 3]

    # All have the same premise
    premises = {item.story_arc_premise for item in items}
    assert len(premises) == 1
    assert "samurai" in premises.pop()

    # All in VIDEO_POLLING status
    for item in items:
        assert item.status == ContentStatus.VIDEO_POLLING.value
        assert item.story_arc_total == 3

    # Script generator was called with arc context
    assert sg.generate_content_script.call_count == 3
    # Third call should have 2 previous scripts
    call_kwargs = sg.generate_content_script.call_args_list[2].kwargs
    assert call_kwargs["arc_chapter"] == 3
    assert call_kwargs["arc_total"] == 3
    assert len(call_kwargs["previous_scripts"]) == 2

    # Video prompt generator was called with arc context
    assert sg.generate_video_prompt.call_count == 3
    call_kwargs = sg.generate_video_prompt.call_args_list[2].kwargs
    assert call_kwargs["arc_chapter"] == 3
    assert len(call_kwargs["previous_video_prompts"]) == 2


def test_arc_chapter_failure_stops_generation(db, arc_bot):
    """If chapter 2 fails, chapter 3 should NOT be generated."""
    fake_script = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}
    call_count = 0

    async def failing_script(bot, topic, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("Gemini rate limit")
        return fake_script

    with patch("app.services.pipeline_orchestrator.script_generator") as sg, \
         patch("app.services.pipeline_orchestrator.video_generator") as vg:

        sg.generate_story_arc_premise = AsyncMock(return_value="premise")
        sg.generate_content_script = AsyncMock(side_effect=failing_script)
        sg.generate_video_prompt = AsyncMock(return_value="prompt")
        vg.submit_video_generation = AsyncMock(return_value="task-1")

        items = asyncio.get_event_loop().run_until_complete(
            run_story_arc_pipeline(arc_bot, db)
        )

    # Only 2 items created (chapter 1 success, chapter 2 failed, no chapter 3)
    assert len(items) == 2
    assert items[0].status == ContentStatus.VIDEO_POLLING.value
    assert items[1].status == ContentStatus.FAILED.value
    assert "Gemini rate limit" in items[1].error_message


def test_arc_pipeline_shared_topic(db, arc_bot):
    """All chapters should share the same topic."""
    fake_script = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}

    with patch("app.services.pipeline_orchestrator.script_generator") as sg, \
         patch("app.services.pipeline_orchestrator.video_generator") as vg:

        sg.generate_story_arc_premise = AsyncMock(return_value="premise")
        sg.generate_content_script = AsyncMock(return_value=fake_script)
        sg.generate_video_prompt = AsyncMock(return_value="prompt")
        vg.submit_video_generation = AsyncMock(return_value="task-1")

        items = asyncio.get_event_loop().run_until_complete(
            run_story_arc_pipeline(arc_bot, db)
        )

    topics = {item.trend_topic for item in items}
    assert len(topics) == 1
    assert "samurai" in topics.pop().lower() or topics  # topic from custom_prompts


# ------------------------------------------------------------------
# Script generator: arc context
# ------------------------------------------------------------------


def test_script_with_arc_context():
    """generate_content_script should pass arc context to Gemini."""
    from app.services import script_generator

    fake_script = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}

    with patch("app.services.script_generator._get_client") as mock_get:
        mock_client = mock_get.return_value
        mock_client.generate_script.return_value = fake_script

        bot = Bot(
            name="T", slug="t", niche="test",
            video_duration_seconds=8,
        )

        result = asyncio.get_event_loop().run_until_complete(
            script_generator.generate_content_script(
                bot, "epic story",
                arc_premise="A hero...",
                arc_chapter=2,
                arc_total=3,
                previous_scripts=[{"hook": "prev", "body": "prev", "cta": "prev"}],
            )
        )

    assert result == fake_script
    # Verify the user_prompt passed to Gemini contains arc context
    call_args = mock_client.generate_script.call_args
    user_prompt = call_args[0][1]  # second positional arg
    assert "Part 2 of 3" in user_prompt
    assert "A hero..." in user_prompt
    assert "Part 1 script" in user_prompt


def test_video_prompt_with_arc_context():
    """generate_video_prompt should pass arc_context to GeminiClient."""
    from app.services import script_generator

    with patch("app.services.script_generator._get_client") as mock_get:
        mock_client = mock_get.return_value
        mock_client.generate_video_prompt.return_value = "cinematic prompt"

        bot = Bot(
            name="T", slug="t", niche="test",
            video_duration_seconds=8,
        )

        result = asyncio.get_event_loop().run_until_complete(
            script_generator.generate_video_prompt(
                bot, {"hook": "H", "body": "B", "cta": "C", "visual_cues": []},
                arc_premise="A hero...",
                arc_chapter=2,
                arc_total=3,
                previous_video_prompts=["previous prompt text"],
            )
        )

    assert result == "cinematic prompt"
    # Verify arc_context was passed
    call_args = mock_client.generate_video_prompt.call_args
    arc_context = call_args[0][2]  # third positional arg
    assert arc_context["chapter"] == 2
    assert arc_context["total"] == 3
    assert "A hero..." in arc_context["premise"]
    assert len(arc_context["previous_prompts"]) == 1


def test_descriptions_with_arc_part():
    """generate_content_descriptions should pass arc info for part labels."""
    from app.services import script_generator

    fake_desc = {
        "instagram": "IG (Parte 2/3)",
        "youtube": {"title": "Title (Parte 2/3)", "description": "desc", "tags": []},
        "tiktok": "TT (Parte 2/3)",
    }

    with patch("app.services.script_generator._get_client") as mock_get:
        mock_client = mock_get.return_value
        mock_client.generate_descriptions.return_value = fake_desc

        bot = Bot(name="T", slug="t", niche="test")

        result = asyncio.get_event_loop().run_until_complete(
            script_generator.generate_content_descriptions(
                bot,
                {"hook": "H", "body": "B", "cta": "C"},
                "topic",
                arc_chapter=2,
                arc_total=3,
            )
        )

    assert result == fake_desc
    # Verify arc kwargs were passed
    call_kwargs = mock_client.generate_descriptions.call_args.kwargs
    assert call_kwargs["arc_chapter"] == 2
    assert call_kwargs["arc_total"] == 3


# ------------------------------------------------------------------
# Scheduler: trigger_now
# ------------------------------------------------------------------


def test_trigger_now_arc_enabled(db, arc_bot):
    """trigger_now should call run_story_arc_pipeline for arc-enabled bots."""
    from app.services import scheduler_service

    fake_items = [
        ContentItem(bot_id=arc_bot.id, story_arc_chapter=1),
        ContentItem(bot_id=arc_bot.id, story_arc_chapter=2),
        ContentItem(bot_id=arc_bot.id, story_arc_chapter=3),
    ]

    with patch.object(
        scheduler_service.pipeline_orchestrator,
        "run_story_arc_pipeline",
        new=AsyncMock(return_value=fake_items),
    ) as mock_arc:
        result = asyncio.get_event_loop().run_until_complete(
            scheduler_service.trigger_now(arc_bot, db)
        )

    assert isinstance(result, list)
    assert len(result) == 3
    mock_arc.assert_called_once_with(arc_bot, db)


def test_trigger_now_no_arc(db):
    """trigger_now should call run_pipeline for non-arc bots."""
    from app.services import scheduler_service

    bot = Bot(
        name="NoArcBot", slug="noarcbot", niche="test",
        story_arc_enabled=False,
    )
    db.add(bot)
    db.commit()

    fake_item = ContentItem(bot_id=bot.id)

    with patch.object(
        scheduler_service.pipeline_orchestrator,
        "run_pipeline",
        new=AsyncMock(return_value=fake_item),
    ) as mock_pipe:
        result = asyncio.get_event_loop().run_until_complete(
            scheduler_service.trigger_now(bot, db)
        )

    assert not isinstance(result, list)
    mock_pipe.assert_called_once_with(bot, db)


# ------------------------------------------------------------------
# Dashboard: content detail with arc siblings
# ------------------------------------------------------------------


def test_content_detail_arc_siblings():
    """Content detail page should show arc navigation for arc items."""
    from app.main import app

    client = TestClient(app)

    from app.database import get_db
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    bot = Bot(name="ArcPageBot", slug="arcpagebot", niche="test",
              story_arc_enabled=True, story_arc_chapters=3)
    db.add(bot)
    db.commit()

    # Create 3 arc items
    for ch in range(1, 4):
        item = ContentItem(
            bot_id=bot.id,
            status=ContentStatus.PENDING_APPROVAL.value,
            story_arc_id="testarc1",
            story_arc_chapter=ch,
            story_arc_total=3,
            story_arc_premise="Test premise",
            trend_topic="Test topic",
        )
        db.add(item)
    db.commit()

    items = db.query(ContentItem).filter(
        ContentItem.story_arc_id == "testarc1"
    ).all()

    response = client.get(f"/bots/{bot.slug}/content/{items[0].id}")
    assert response.status_code == 200
    assert "arc-chapter-link" in response.text
    assert "Cap 1" in response.text
    assert "Cap 2" in response.text
    assert "Cap 3" in response.text
    assert "Test premise" in response.text


def test_content_list_arc_badge():
    """Content list should show arc badges for arc items."""
    from app.main import app

    client = TestClient(app)

    from app.database import get_db
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    bot = Bot(name="ArcListBot", slug="arclistbot", niche="test")
    db.add(bot)
    db.commit()

    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.VIDEO_POLLING.value,
        story_arc_id="listarc1",
        story_arc_chapter=2,
        story_arc_total=3,
        trend_topic="Arc topic",
    )
    db.add(item)
    db.commit()

    response = client.get(f"/bots/{bot.slug}/content")
    assert response.status_code == 200
    assert "arc-badge" in response.text
    assert "Cap 2/3" in response.text
