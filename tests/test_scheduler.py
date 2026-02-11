"""Tests for scheduler_service -- tests scheduling, unscheduling, and trigger_now."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.bot import Bot
from app.services.scheduler_service import (
    _job_id_for_bot,
    init_scheduler,
    get_scheduler,
    schedule_bot,
    schedule_video_polling,
    unschedule_bot,
    schedule_all_bots,
    trigger_now,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def setup_scheduler():
    """Initialize a fresh scheduler for each test."""
    sched = init_scheduler()
    yield sched
    # Don't start/stop in tests -- just cleanup
    import app.services.scheduler_service as ss
    ss.scheduler = None


@pytest.fixture
def bot(db):
    b = Bot(
        name="SchedBot",
        slug="schedbot",
        niche="fitness",
        is_enabled=True,
        posting_schedule={"times": ["09:00", "18:00"], "timezone": "Europe/Madrid"},
    )
    db.add(b)
    db.commit()
    return b


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_init_scheduler():
    """Should return a scheduler instance."""
    sched = init_scheduler()
    assert sched is not None


def test_get_scheduler():
    """Should return the same instance."""
    sched = get_scheduler()
    assert sched is not None


def test_get_scheduler_not_initialized():
    """Should raise if scheduler not init'd."""
    import app.services.scheduler_service as ss
    ss.scheduler = None
    with pytest.raises(RuntimeError, match="not initialized"):
        get_scheduler()
    # Restore for other tests
    init_scheduler()


def test_job_id_for_bot():
    assert _job_id_for_bot(42) == "bot_pipeline_42"


def test_schedule_bot_enabled(bot):
    """Enabled bot should get jobs scheduled."""
    schedule_bot(bot)
    sched = get_scheduler()
    # Should have 2 jobs (one for 09:00, one for 18:00)
    main_job = sched.get_job(_job_id_for_bot(bot.id))
    extra_job = sched.get_job(f"{_job_id_for_bot(bot.id)}_1")
    assert main_job is not None
    assert extra_job is not None


def test_schedule_bot_disabled(db):
    """Disabled bot should not be scheduled."""
    b = Bot(name="Disabled", slug="disabled", niche="tech", is_enabled=False)
    db.add(b)
    db.commit()

    schedule_bot(b)
    sched = get_scheduler()
    assert sched.get_job(_job_id_for_bot(b.id)) is None


def test_unschedule_bot(bot):
    """Should remove all jobs for a bot."""
    schedule_bot(bot)
    sched = get_scheduler()
    assert sched.get_job(_job_id_for_bot(bot.id)) is not None

    unschedule_bot(bot.id)
    assert sched.get_job(_job_id_for_bot(bot.id)) is None
    assert sched.get_job(f"{_job_id_for_bot(bot.id)}_1") is None


def test_schedule_video_polling():
    """Should add the video_polling interval job."""
    schedule_video_polling()
    sched = get_scheduler()
    job = sched.get_job("video_polling")
    assert job is not None
    assert "30" in str(job.trigger)  # IntervalTrigger(seconds=30)


def test_schedule_all_bots(db, bot):
    """Should schedule all enabled bots."""
    # Add a disabled bot
    disabled = Bot(name="DisB", slug="disb", niche="tech", is_enabled=False)
    db.add(disabled)
    db.commit()

    schedule_all_bots(db)
    sched = get_scheduler()

    # Enabled bot should be scheduled
    assert sched.get_job(_job_id_for_bot(bot.id)) is not None
    # Disabled bot should not
    assert sched.get_job(_job_id_for_bot(disabled.id)) is None


def test_trigger_now(db, bot):
    """trigger_now should call pipeline_orchestrator.run_pipeline."""
    mock_content = MagicMock()
    mock_content.id = 99

    with patch("app.services.scheduler_service.pipeline_orchestrator") as mock_po:
        mock_po.run_pipeline = AsyncMock(return_value=mock_content)

        result = asyncio.get_event_loop().run_until_complete(
            trigger_now(bot, db)
        )

    assert result.id == 99
    mock_po.run_pipeline.assert_called_once_with(bot, db)
