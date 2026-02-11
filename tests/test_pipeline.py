"""Tests for pipeline_orchestrator -- mocks all external services."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.models.log_entry import PipelineLog
from app.services.pipeline_orchestrator import (
    _log,
    _select_topic,
    _set_error,
    _set_status,
    resume_after_approval,
    resume_after_video,
    run_pipeline,
)


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
def bot(db):
    """Insert a minimal Bot into the test DB."""
    b = Bot(
        name="PipelineTestBot",
        slug="pipelinetestbot",
        niche="fitness",
        niche_description="Fitness tips and tricks",
        content_style="motivational",
        language="es",
        video_provider="kling3",
        video_duration_seconds=15,
        custom_prompts=["5 ejercicios rapidos", "Dieta saludable"],
    )
    db.add(b)
    db.commit()
    return b


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def test_select_topic_custom_prompts(bot, db):
    """Should return the first custom prompt when use_trends is False."""
    bot.use_trends = False
    db.commit()
    topic = _select_topic(bot, db)
    assert topic == "5 ejercicios rapidos"


def test_select_topic_no_prompts(db):
    """Should return a default topic based on niche."""
    b = Bot(name="NoPB", slug="nopb", niche="tech", use_trends=False)
    db.add(b)
    db.commit()
    topic = _select_topic(b, db)
    assert "tech" in topic


def test_log_creates_entry(db, bot):
    """_log should insert a PipelineLog row."""
    _log(db, bot.id, None, "test_stage", "test message")
    logs = db.query(PipelineLog).all()
    assert len(logs) == 1
    assert logs[0].stage == "test_stage"
    assert logs[0].message == "test message"


def test_set_status(db, bot):
    """_set_status should update content status."""
    item = ContentItem(bot_id=bot.id)
    db.add(item)
    db.commit()

    _set_status(db, item, ContentStatus.SCRIPT_GENERATING)
    db.refresh(item)
    assert item.status == "script_generating"


def test_set_error(db, bot):
    """_set_error should set status to FAILED with error message."""
    item = ContentItem(bot_id=bot.id)
    db.add(item)
    db.commit()

    _set_error(db, item, "Something went wrong")
    db.refresh(item)
    assert item.status == "failed"
    assert item.error_message == "Something went wrong"
    assert item.retry_count == 1


# ------------------------------------------------------------------
# Phase 1: run_pipeline
# ------------------------------------------------------------------


def test_run_pipeline_success(db, bot):
    """Full Phase 1 should create a content item in video_polling status."""
    fake_script = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}

    bot.use_trends = False
    db.commit()

    with patch("app.services.pipeline_orchestrator.script_generator") as sg, \
         patch("app.services.pipeline_orchestrator.video_generator") as vg:

        sg.generate_content_script = AsyncMock(return_value=fake_script)
        sg.generate_video_prompt = AsyncMock(return_value="cinematic prompt")
        vg.submit_video_generation = AsyncMock(return_value="task-123")

        content = asyncio.get_event_loop().run_until_complete(
            run_pipeline(bot, db)
        )

    assert content.status == ContentStatus.VIDEO_POLLING.value
    assert content.video_task_id == "task-123"
    assert content.trend_topic == "5 ejercicios rapidos"
    assert content.script is not None
    assert content.video_prompt == "cinematic prompt"

    # Should have created pipeline log entries
    logs = db.query(PipelineLog).filter(PipelineLog.content_id == content.id).all()
    assert len(logs) >= 3


def test_run_pipeline_script_error(db, bot):
    """Script generation failure should set content to FAILED."""
    with patch("app.services.pipeline_orchestrator.script_generator") as sg, \
         patch("app.services.pipeline_orchestrator.video_generator"):

        sg.generate_content_script = AsyncMock(
            side_effect=Exception("Gemini API down")
        )

        with pytest.raises(Exception, match="Gemini API down"):
            asyncio.get_event_loop().run_until_complete(
                run_pipeline(bot, db)
            )

    # Content should exist and be in FAILED state
    items = db.query(ContentItem).filter(ContentItem.bot_id == bot.id).all()
    assert len(items) == 1
    assert items[0].status == ContentStatus.FAILED.value
    assert "Gemini API down" in items[0].error_message


# ------------------------------------------------------------------
# Phase 2: resume_after_video
# ------------------------------------------------------------------


def test_resume_after_video_completed(db, bot):
    """Phase 2 with completed video should generate descriptions and send for approval."""
    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.VIDEO_POLLING.value,
        video_task_id="task-123",
        trend_topic="fitness tips",
        script=json.dumps({"hook": "H", "body": "B", "cta": "C", "visual_cues": []}),
    )
    db.add(item)
    db.commit()

    # Set telegram_chat_id so approval can be sent
    bot.telegram_chat_id = "12345"
    db.commit()

    descriptions = {
        "instagram": "IG caption",
        "youtube": {"title": "YT title", "description": "YT desc", "tags": ["fit"]},
        "tiktok": "TT caption",
    }

    with patch("app.services.pipeline_orchestrator.video_generator") as vg, \
         patch("app.services.pipeline_orchestrator.script_generator") as sg:

        vg.check_video_status = AsyncMock(
            return_value={"status": "completed", "video_url": "https://cdn/video.mp4"}
        )
        vg.download_video = AsyncMock(return_value="/tmp/video.mp4")
        sg.generate_content_descriptions = AsyncMock(return_value=descriptions)

        result = asyncio.get_event_loop().run_until_complete(
            resume_after_video(item, bot, db)
        )

    assert result.status == ContentStatus.PENDING_APPROVAL.value
    assert result.video_file_path == "/tmp/video.mp4"
    assert result.description_instagram == "IG caption"
    assert "YT title" in result.description_youtube
    assert result.description_tiktok == "TT caption"
    assert result.approval_status == "pending"


def test_resume_after_video_failed(db, bot):
    """Phase 2 with failed video should set content to FAILED."""
    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.VIDEO_POLLING.value,
        video_task_id="task-456",
    )
    db.add(item)
    db.commit()

    bot.telegram_chat_id = "12345"
    db.commit()

    with patch("app.services.pipeline_orchestrator.video_generator") as vg, \
         patch("app.services.pipeline_orchestrator.script_generator"):

        vg.check_video_status = AsyncMock(
            return_value={"status": "failed", "error": "GPU error"}
        )

        result = asyncio.get_event_loop().run_until_complete(
            resume_after_video(item, bot, db)
        )

    assert result.status == ContentStatus.FAILED.value
    assert "GPU error" in result.error_message


def test_resume_after_video_still_processing(db, bot):
    """Phase 2 with still-processing video should not change status."""
    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.VIDEO_POLLING.value,
        video_task_id="task-789",
    )
    db.add(item)
    db.commit()

    with patch("app.services.pipeline_orchestrator.video_generator") as vg, \
         patch("app.services.pipeline_orchestrator.script_generator"):

        vg.check_video_status = AsyncMock(
            return_value={"status": "processing"}
        )

        result = asyncio.get_event_loop().run_until_complete(
            resume_after_video(item, bot, db)
        )

    assert result.status == ContentStatus.VIDEO_POLLING.value


# ------------------------------------------------------------------
# Phase 3: resume_after_approval
# ------------------------------------------------------------------


def test_resume_after_approval_no_credentials(db, bot):
    """Approved content with no platform credentials should be marked published."""
    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.APPROVED.value,
        approval_status="approved",
    )
    db.add(item)
    db.commit()

    bot.telegram_chat_id = "12345"
    db.commit()

    with patch("app.services.pipeline_orchestrator.publisher") as pub:
        pub.publish_to_all = AsyncMock(return_value={})

        result = asyncio.get_event_loop().run_until_complete(
            resume_after_approval(item, bot, db)
        )

    assert result.status == ContentStatus.PUBLISHED.value
    assert result.completed_at is not None


def test_resume_after_approval_not_approved(db, bot):
    """Non-approved content should be skipped."""
    item = ContentItem(
        bot_id=bot.id,
        status=ContentStatus.REJECTED.value,
        approval_status="rejected",
    )
    db.add(item)
    db.commit()

    with patch("app.services.pipeline_orchestrator.publisher"):
        result = asyncio.get_event_loop().run_until_complete(
            resume_after_approval(item, bot, db)
        )

    # Status should not change to PUBLISHING
    assert result.status == ContentStatus.REJECTED.value
